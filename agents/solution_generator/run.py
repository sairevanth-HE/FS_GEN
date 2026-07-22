"""A-03: Solution Generator — async run."""

from __future__ import annotations

import json
import time
from pathlib import Path

import structlog

from agents.base import parse_json_result, run_agent, scaled_max_tokens
from agents.solution_generator.prompt import AGENT_ID, AGENT_NAME, SYSTEM_PROMPT
from agents.stack_specs import REACT_STACKS, STACK_PLAYBOOKS, STACKS, UNIVERSAL_RULES
from agents.tools import SOLUTION_GENERATOR_HANDLERS, SOLUTION_GENERATOR_TOOL_DEFS
from services import db

logger = structlog.getLogger(__name__)


async def run(question_id: str, output_dir: str, stack: str, difficulty: str, design: dict) -> dict:
    """Write the solution under <output_dir>/solution/ mirroring the skeleton tree."""
    start = time.monotonic()
    log = logger.bind(question_id=question_id, agent=AGENT_ID)
    skeleton_dir = str(Path(output_dir) / "skeleton")
    solution_dir = str(Path(output_dir) / "solution")
    max_iters = 100 if stack in REACT_STACKS else 80

    system_prompt = (f"{SYSTEM_PROMPT}\n{UNIVERSAL_RULES}\n{STACK_PLAYBOOKS[stack]}"
                     f"{await db.db_get_stack_lessons_block(stack)}")
    user_message = f"""Generate the solution:
question_id:  {question_id}
stack:        {STACKS[stack]}
difficulty:   {difficulty}
skeleton_dir: {skeleton_dir}
solution_dir: {solution_dir}

Design (the contracts and logic-complexity items to implement):
{json.dumps({k: v for k, v in design.items() if k != "status"}, indent=2)}

Steps:
1. list_files(directory="{skeleton_dir}") and read_file every skeleton file.
2. Write the full solution tree with write_files(files={{...}}, output_dir="{solution_dir}") —
   identical paths, every stub implemented, infrastructure copied through unchanged.
3. diff_file_trees(dir1="{skeleton_dir}", dir2="{solution_dir}") — fix any mismatch until parity_ok.
4. Respond with ONLY: {{"question_id": "{question_id}", "solution_dir": "{solution_dir}", "files_written": <count>, "parity_ok": true}}
"""

    result_text, tokens = await run_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        tools=SOLUTION_GENERATOR_TOOL_DEFS,
        tool_handlers=SOLUTION_GENERATOR_HANDLERS,
        max_tokens=scaled_max_tokens(32000, difficulty),
        max_tool_iterations=max_iters,
    )

    duration = time.monotonic() - start

    try:
        result = parse_json_result(result_text)
        result["status"] = result.get("status", "done")
        await db.db_log_agent(
            question_id=question_id,
            agent_id=AGENT_ID,
            agent_name=AGENT_NAME,
            status="success",
            logs=f"solution_dir={solution_dir} files_written={result.get('files_written')}",
            duration_seconds=duration,
            tokens_used=tokens,
        )
        log.info("solution_done", solution_dir=solution_dir, tokens=tokens)
        return result
    except json.JSONDecodeError:
        log.error("solution_parse_error", result_text=result_text[:500])
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
