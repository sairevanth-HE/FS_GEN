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
import time
from pathlib import Path

import structlog

from agents.base import run_agent, scaled_max_tokens
from agents.stack_specs import STACK_PLAYBOOKS, UNIVERSAL_RULES
from agents.validator.prompt import AGENT_ID, AGENT_NAME, FIXER_SYSTEM_PROMPT
from agents.tools import TEST_GENERATOR_HANDLERS, TEST_GENERATOR_TOOL_DEFS
from services import db, test_runner

logger = structlog.getLogger(__name__)

# Keep fixing while rounds still make progress; stop after 2 stalled rounds or the hard cap.
MAX_FIX_ROUNDS = 5
FIXER_MAX_TOKENS = 20000  # flat — a truncated fix is worse than a costly one


def _summary(results: list[test_runner.SuiteResult]) -> str:
    return "; ".join(f"{r.suite}: {r.passed}p/{r.failed}f{'' if r.ok else ' FAIL'}" for r in results)


def _failure_report(results: list[test_runner.SuiteResult]) -> str:
    parts = [f"## {r.suite} (exit not ok — {r.passed} passed, {r.failed} failed)\n{r.output}"
             for r in results if not r.ok]
    return "\n\n".join(parts)


async def _fix(question_id: str, output_dir: str, stack: str, difficulty: str,
               design_json: str, instruction: str, report: str) -> int:
    system_prompt = f"{FIXER_SYSTEM_PROMPT}\n{UNIVERSAL_RULES}\n{STACK_PLAYBOOKS[stack]}"
    user_message = f"""{instruction}
question_id:  {question_id}
skeleton_dir: {Path(output_dir) / 'skeleton'}
solution_dir: {Path(output_dir) / 'solution'}

Design (the contract — decides whether a test or the solution is wrong):
{design_json}

Actual run output:
{report}

Respond with ONLY: {{"question_id": "{question_id}", "files_changed": [...], "summary": "..."}}"""
    _, tokens = await run_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        tools=TEST_GENERATOR_TOOL_DEFS,
        tool_handlers=TEST_GENERATOR_HANDLERS,
        max_tokens=FIXER_MAX_TOKENS,
    )
    return tokens


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

    # Gate 1: every suite green on the solution.
    try:
        results = await asyncio.to_thread(test_runner.run_part_suites, stack, solution_dir)
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
            log.info("validation_fix_round", round=rounds, results=_summary(res))
            tokens += await _fix(question_id, output_dir, stack, difficulty, design_json,
                                 "Fix these REAL test-run failures (Gate 1: solution must pass):",
                                 _failure_report(res))
            res = await asyncio.to_thread(test_runner.run_part_suites, stack, solution_dir)
            stalled = stalled + 1 if _badness(res) >= before else 0
        return res

    results = await _fix_loop(results, MAX_FIX_ROUNDS)
    if any(not r.ok for r in results):
        await _log("failed", f"solution suites still failing after {rounds} fix rounds: {_summary(results)}")
        log.error("validation_failed", results=_summary(results))
        return {"question_id": question_id, "status": "failed",
                "error": f"tests failing after {rounds} fix rounds: {_summary(results)}"}

    # Gate 2: hidden suite must fail on the skeleton (tests require candidate logic).
    try:
        skel = await asyncio.to_thread(test_runner.run_part_suites, stack, skeleton_dir, ["hidden"])
    except test_runner.RunnerUnavailable as exc:
        await _log("success", f"solution green ({_summary(results)}); skeleton check skipped: {exc}")
        return {"question_id": question_id, "status": "done", "fix_rounds": rounds,
                "validation": "solution_only"}

    skel_passing = sum(r.passed for r in skel)
    if skel_passing:
        log.info("skeleton_passing_tests", count=skel_passing)
        tokens += await _fix(
            question_id, output_dir, stack, difficulty, design_json,
            f"Gate 2 violation: {skel_passing} hidden test(s) PASS against the skeleton stubs — "
            "they test nothing the candidate writes. Strengthen exactly those tests (in BOTH "
            "dirs) so they require real logic, without breaking the solution run:",
            "\n\n".join(f"## {r.suite} on SKELETON — {r.passed} passed (should be 0)\n{r.output}"
                        for r in skel))
        results = await asyncio.to_thread(test_runner.run_part_suites, stack, solution_dir)
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

    logs = (f"solution green: {_summary(results)} | skeleton hidden: "
            f"{sum(r.failed for r in skel)} failing / {skel_passing} passing | fix_rounds={rounds}")
    await _log("success", logs)
    log.info("validation_done", fix_rounds=rounds, skeleton_passing=skel_passing)
    return {"question_id": question_id, "status": "done", "fix_rounds": rounds,
            "solution_suites": [vars(r) | {"output": ""} for r in results],
            "skeleton_passing_hidden": skel_passing}
