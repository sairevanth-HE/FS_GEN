"""A-06: Validator — execute the generated suites and fix until the gates hold.

Gates: solution passes every suite; hidden tests fail on the skeleton.
QOS policy: if this machine can't execute (missing runtime, install failure),
validation is SKIPPED with a warning — generation still completes. If the
suites run and can't be made green within the fix budget, the question FAILS —
a question with broken tests is never shipped.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path

import structlog

from agents.base import parse_json_result, run_agent, scaled_max_tokens
from agents.stack_specs import REACT_STACKS, STACK_PLAYBOOKS, UNIVERSAL_RULES
from agents.validator.prompt import AGENT_ID, AGENT_NAME, FIXER_SYSTEM_PROMPT
from agents.tools import TEST_GENERATOR_HANDLERS, TEST_GENERATOR_TOOL_DEFS
from services import db, test_runner

logger = structlog.getLogger(__name__)


def _max_fix_rounds(stack: str) -> int:
    """React pairings surface multi-front failures (backend + frontend + boot check) in
    the same run — 5 rounds sized for one coherent backend-only failure isn't enough."""
    return 7 if stack in REACT_STACKS else 5


def _fixer_max_tokens(stack: str, difficulty: str) -> int:
    """Fixer needs more room on React pairings (multi-front failures: backend +
    frontend + boot check can all need diagnosis/patching in one round) and on
    harder difficulties (more entities/endpoints/logic-complexity items to reason
    about). Flat 20000 was sized for a single backend-only file, not this."""
    base = 32000 if stack in REACT_STACKS else 20000
    return scaled_max_tokens(base, difficulty)


def _summary(results: list[test_runner.SuiteResult]) -> str:
    return "; ".join(f"{r.suite}: {r.passed}p/{r.failed}f{'' if r.ok else ' FAIL'}" for r in results)


def _failure_report(results: list[test_runner.SuiteResult]) -> str:
    parts = [f"## {r.suite} (exit not ok — {r.passed} passed, {r.failed} failed)\n{r.output}"
             for r in results if not r.ok]
    return "\n\n".join(parts)


_STALL_NOTE = ("NOTE: your previous fix changed NOTHING — the exact same failures repeat, so the "
               "earlier diagnosis was wrong. Do not repeat that patch. Re-read the failing test AND "
               "the code it hits and look for a different root cause.\n")

_TEST_NAME_RE = re.compile(r"^\s*def (test_\w+)|(?:\bit|\btest)\s*\(\s*['\"](.+?)['\"]", re.M)


def _sample_subset_warning(solution_dir: str) -> str | None:
    """Deterministic backstop for the prompt rule 'sample suite ⊆ hidden suite':
    every test NAME in a sample file must also exist in a hidden file."""
    sample: set[str] = set()
    hidden: set[str] = set()
    for p in Path(solution_dir).rglob("*"):
        if p.suffix not in (".py", ".js") or "test" not in p.name.lower():
            continue
        names = {a or b for a, b in _TEST_NAME_RE.findall(p.read_text(errors="replace"))}
        (sample if "sample" in p.name.lower() else hidden).update(names)
    extras = sample - hidden
    if extras:
        return f"sample suite drifted from hidden suite — sample-only tests: {sorted(extras)}"
    return None


async def _fix(question_id: str, output_dir: str, stack: str, difficulty: str,
               design_json: str, instruction: str, report: str) -> tuple[int, str]:
    system_prompt = (f"{FIXER_SYSTEM_PROMPT}\n{UNIVERSAL_RULES}\n{STACK_PLAYBOOKS[stack]}"
                     f"{await db.db_get_stack_lessons_block(stack)}")
    user_message = f"""{instruction}
question_id:  {question_id}
skeleton_dir: {Path(output_dir) / 'skeleton'}
solution_dir: {Path(output_dir) / 'solution'}

If your fix touches a test file (test.py, sample_test.py, *.test.js), apply the identical change
to the copy in BOTH skeleton_dir and solution_dir — they must stay byte-identical. A fix that
patches a bug in only one copy (e.g. a session/detached-instance issue in the test itself) leaves
the other copy broken even though the solution passes.

Design (the contract — decides whether a test or the solution is wrong):
{design_json}

Actual run output:
{report}

Respond with ONLY: {{"question_id": "{question_id}", "files_changed": [...], "summary": "..."}}"""
    result_text, tokens = await run_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        tools=TEST_GENERATOR_TOOL_DEFS,
        tool_handlers=TEST_GENERATOR_HANDLERS,
        max_tokens=_fixer_max_tokens(stack, difficulty),
    )
    summary = ""
    try:
        summary = parse_json_result(result_text).get("summary", "") or ""
    except json.JSONDecodeError:
        pass
    return tokens, summary


async def run(question_id: str, output_dir: str, stack: str, difficulty: str, design: dict) -> dict:
    """Execute suites; loop fixer until solution is green and skeleton fails the hidden suite."""
    start = time.monotonic()
    log = logger.bind(question_id=question_id, agent=AGENT_ID)
    solution_dir = str(Path(output_dir) / "solution")
    skeleton_dir = str(Path(output_dir) / "skeleton")
    design_json = json.dumps({k: v for k, v in design.items() if k != "status"}, indent=2)
    tokens = 0

    async def _log(status: str, logs: str) -> None:
        await db.db_log_agent(question_id=question_id, agent_id=AGENT_ID, agent_name=AGENT_NAME,
                              status=status, logs=logs, duration_seconds=time.monotonic() - start,
                              tokens_used=tokens)

    def _solution_gate() -> list:
        """Gate 1 = the test suites PLUS an app-boot smoke test. The boot check catches
        a crash-on-startup (e.g. a seed FK error) that the suites miss, and it rides the
        same fix loop so the fixer sees the crash output and repairs it."""
        res = test_runner.run_part_suites(stack, solution_dir)
        boot = test_runner.boot_check(stack, solution_dir)
        return res + [boot] if boot is not None else res

    # Gate 1: every suite green on the solution AND the app boots without crashing.
    log.info("gate1_start", target="solution", suites="all+boot")
    try:
        results = await asyncio.to_thread(_solution_gate)
    except test_runner.RunnerUnavailable as exc:
        log.warning("validation_skipped", reason=str(exc))
        await _log("success", f"validation SKIPPED (runner unavailable): {exc}")
        return {"question_id": question_id, "status": "done", "validation": "skipped",
                "reason": str(exc)}

    def _badness(res: list[test_runner.SuiteResult]) -> int:
        # A suite that didn't even load (0 tests seen) is worse than any failure count.
        return sum(100 if (r.passed + r.failed == 0) else r.failed for r in res if not r.ok)

    rounds = 0

    async def _fix_loop(res: list, budget: int) -> list:
        """Fix → rerun until green, the budget runs out, or 2 rounds without progress."""
        nonlocal tokens, rounds
        spent = stalled = 0
        while any(not r.ok for r in res) and spent < budget and stalled < 2:
            spent += 1
            rounds += 1
            before = _badness(res)
            log.info("validation_fix_round", round=rounds, budget=budget, results=_summary(res))
            round_start = time.monotonic()
            round_tokens, summary = await _fix(
                question_id, output_dir, stack, difficulty, design_json,
                (_STALL_NOTE if stalled else "")
                + "Fix these REAL test-run failures (Gate 1: solution must pass):",
                _failure_report(res))
            tokens += round_tokens
            res = await asyncio.to_thread(_solution_gate)
            after = _badness(res)
            if after < before and summary:
                await db.db_record_stack_lesson(stack, summary)
            stalled = stalled + 1 if after >= before else 0
            # Per-round evidence in the DB so a failed question is debuggable without a rerun.
            # tokens_used stays in the text only — the final summary row carries the cumulative
            # count, and double-logging would inflate the per-question token sum.
            await db.db_log_agent(
                question_id=question_id, agent_id=AGENT_ID, agent_name=AGENT_NAME,
                status="fix_round",
                logs=(f"round {rounds}: badness {before}→{_badness(res)} "
                      f"(stalled={stalled}, round_tokens={round_tokens}) | {_summary(res)}"),
                duration_seconds=time.monotonic() - round_start)
        return res

    results = await _fix_loop(results, _max_fix_rounds(stack))
    if any(not r.ok for r in results):
        await _log("failed", f"solution suites still failing after {rounds} fix rounds: {_summary(results)}")
        log.error("validation_failed", results=_summary(results))
        return {"question_id": question_id, "status": "failed",
                "error": f"tests failing after {rounds} fix rounds: {_summary(results)}"}

    # Gate 2: hidden suite must fail on the skeleton (tests require candidate logic).
    log.info("gate2_start", target="skeleton", suites="hidden", expectation="must fail")
    try:
        skel = await asyncio.to_thread(test_runner.run_part_suites, stack, skeleton_dir, ["hidden"])
    except test_runner.RunnerUnavailable as exc:
        log.warning("skeleton_check_skipped", reason=str(exc))
        await _log("success", f"solution green ({_summary(results)}); skeleton check skipped: {exc}")
        return {"question_id": question_id, "status": "done", "fix_rounds": rounds,
                "validation": "solution_only"}

    skel_passing = sum(r.passed for r in skel)
    if skel_passing:
        log.info("skeleton_passing_tests", count=skel_passing, action="strengthening")
        strengthen_tokens, strengthen_summary = await _fix(
            question_id, output_dir, stack, difficulty, design_json,
            f"Gate 2 violation: {skel_passing} hidden test(s) PASS against the skeleton stubs — "
            "they test nothing the candidate writes. Strengthen exactly those tests (in BOTH "
            "dirs) so they require real logic, without breaking the solution run:",
            "\n\n".join(f"## {r.suite} on SKELETON — {r.passed} passed (should be 0)\n{r.output}"
                        for r in skel))
        tokens += strengthen_tokens
        if strengthen_summary:
            await db.db_record_stack_lesson(stack, strengthen_summary)
        results = await asyncio.to_thread(_solution_gate)
        # Strengthening can break the solution run — repair with a small extra fix budget.
        results = await _fix_loop(results, 2)
        if any(not r.ok for r in results):
            await _log("failed", f"strengthening broke the solution run: {_summary(results)}")
            return {"question_id": question_id, "status": "failed",
                    "error": f"solution suites broken after strengthening: {_summary(results)}"}
        skel = await asyncio.to_thread(test_runner.run_part_suites, stack, skeleton_dir, ["hidden"])
        skel_passing = sum(r.passed for r in skel)

    if all(r.failed == 0 for r in skel):
        await _log("failed", "hidden suite fully passes on the skeleton — the tests have no teeth")
        return {"question_id": question_id, "status": "failed",
                "error": "hidden suite passes on the untouched skeleton"}

    # Non-fatal drift guard: the fixer prompt requires sample ⊆ hidden; verify it held.
    if warn := _sample_subset_warning(solution_dir):
        log.warning("sample_subset_violation", detail=warn)
        await db.db_log_agent(question_id=question_id, agent_id=AGENT_ID, agent_name=AGENT_NAME,
                              status="warning", logs=warn)

    logs = (f"solution green: {_summary(results)} | skeleton hidden: "
            f"{sum(r.failed for r in skel)} failing / {skel_passing} passing | fix_rounds={rounds}")
    await _log("success", logs)
    log.info("validation_done", symmetry="ok", fix_rounds=rounds,
             skeleton_failing=sum(r.failed for r in skel), skeleton_passing=skel_passing,
             tokens=tokens)
    return {"question_id": question_id, "status": "done", "fix_rounds": rounds,
            "solution_suites": [vars(r) | {"output": ""} for r in results],
            "skeleton_passing_hidden": skel_passing}
