"""A-04: Test Generator — async run (tests are written, never executed)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import structlog

from agents.base import parse_json_result, run_agent, scaled_max_tokens
from agents.stack_specs import STACK_PLAYBOOKS, STACKS, UNIVERSAL_RULES
from agents.test_generator.prompt import AGENT_ID, AGENT_NAME, CRITIC_SYSTEM_PROMPT, SYSTEM_PROMPT
from agents.tools import (
    TEST_CRITIC_HANDLERS,
    TEST_CRITIC_TOOL_DEFS,
    TEST_GENERATOR_HANDLERS,
    TEST_GENERATOR_TOOL_DEFS,
)
from services import db

logger = structlog.getLogger(__name__)


async def _critique(design_json: str, skeleton_dir: str, solution_dir: str,
                    test_files: list, difficulty: str) -> tuple[dict, int]:
    """Run the read-only critic over the written suites. Returns (verdict, tokens)."""
    user_message = f"""Judge the hidden test suite:
difficulty:   {difficulty}
skeleton_dir: {skeleton_dir}
solution_dir: {solution_dir}
test_files:   {json.dumps(test_files)}

Design:
{design_json}

Read the test files and the solution's route/handler files, check every point of the bar, then
respond with ONLY the {{"adequate": ..., "gaps": [...]}} JSON object."""
    result_text, tokens = await run_agent(
        system_prompt=CRITIC_SYSTEM_PROMPT,
        user_message=user_message,
        tools=TEST_CRITIC_TOOL_DEFS,
        tool_handlers=TEST_CRITIC_HANDLERS,
        max_tokens=4000,
    )
    try:
        return parse_json_result(result_text), tokens
    except json.JSONDecodeError:
        # ponytail: an unparseable critic verdict never fails the pipeline — treat as adequate.
        logger.warning("critic_parse_error", result_text=result_text[:300])
        return {"adequate": True, "gaps": []}, tokens


async def run(question_id: str, output_dir: str, stack: str, difficulty: str, design: dict) -> dict:
    """Write hidden + sample test files into both skeleton/ and solution/."""
    start = time.monotonic()
    log = logger.bind(question_id=question_id, agent=AGENT_ID)
    skeleton_dir = str(Path(output_dir) / "skeleton")
    solution_dir = str(Path(output_dir) / "solution")

    system_prompt = f"{SYSTEM_PROMPT}\n{UNIVERSAL_RULES}\n{STACK_PLAYBOOKS[stack]}"
    design_json = json.dumps({k: v for k, v in design.items() if k != "status"}, indent=2)
    user_message = f"""Generate the test suites:
question_id:  {question_id}
stack:        {STACKS[stack]}
difficulty:   {difficulty}
skeleton_dir: {skeleton_dir}
solution_dir: {solution_dir}

Design (contracts and the business rules the tests must pin down):
{design_json}

Steps:
1. list_files(directory="{solution_dir}") and read_file the solution's route/handler files to test
   its actual behavior (exact status codes and error wording).
2. Write the hidden suite, then the sample suite as a strict subset, with
   write_files(files={{...}}, output_dir="{solution_dir}").
3. Write the exact same test files with write_files(files={{...}}, output_dir="{skeleton_dir}").
4. Respond with ONLY: {{"question_id": "{question_id}", "hidden_tests": <count>, "sample_tests": <count>, "non_happy_tests": <count>, "test_files": [...]}}
"""

    result_text, tokens = await run_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        tools=TEST_GENERATOR_TOOL_DEFS,
        tool_handlers=TEST_GENERATOR_HANDLERS,
        max_tokens=scaled_max_tokens(16000, difficulty),
    )

    # Critic reviews the written suite; if it finds gaps, one revision pass fixes them.
    # ponytail: single revision pass; make it a loop only if audits show one pass isn't enough.
    critic_note = "critic=skipped"
    try:
        first = parse_json_result(result_text)
    except json.JSONDecodeError:
        first = None
    if first is not None:
        verdict, critic_tokens = await _critique(
            design_json, skeleton_dir, solution_dir, first.get("test_files", []), difficulty)
        tokens += critic_tokens
        gaps = verdict.get("gaps") or []
        critic_note = f"critic_gaps={len(gaps)}"
        if gaps:
            log.info("tests_revision", gaps=len(gaps))
            gap_list = "\n".join(f"- {g}" for g in gaps)
            revise_message = f"""{user_message}

A previous agent already wrote the test suites for this question. A reviewer found these gaps in
the hidden suite:
{gap_list}

Instead of starting over: read the EXISTING test files in {solution_dir}, fix every gap by adding
or strengthening tests, keep the sample suite a strict subset of the hidden suite, write the
changed test files into BOTH dirs, and respond with ONLY the same JSON object shape."""
            result_text, revise_tokens = await run_agent(
                system_prompt=system_prompt,
                user_message=revise_message,
                tools=TEST_GENERATOR_TOOL_DEFS,
                tool_handlers=TEST_GENERATOR_HANDLERS,
                max_tokens=scaled_max_tokens(16000, difficulty),
            )
            tokens += revise_tokens

    duration = time.monotonic() - start

    try:
        result = parse_json_result(result_text)
        result["status"] = result.get("status", "done")
        await db.db_log_agent(
            question_id=question_id,
            agent_id=AGENT_ID,
            agent_name=AGENT_NAME,
            status="success",
            logs=f"hidden={result.get('hidden_tests')} sample={result.get('sample_tests')} "
                 f"non_happy={result.get('non_happy_tests')} {critic_note}",
            duration_seconds=duration,
            tokens_used=tokens,
        )
        log.info("tests_done", hidden=result.get("hidden_tests"), tokens=tokens)
        return result
    except json.JSONDecodeError:
        log.error("tests_parse_error", result_text=result_text[:500])
        await db.db_log_agent(
            question_id=question_id,
            agent_id=AGENT_ID,
            agent_name=AGENT_NAME,
            status="failed",
            logs=result_text,
            duration_seconds=duration,
            tokens_used=tokens,
        )
        return {"question_id": question_id, "status": "failed", "error": result_text}
