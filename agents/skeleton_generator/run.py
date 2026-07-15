"""A-02: Skeleton Generator — async run."""

from __future__ import annotations

import json
import time
from pathlib import Path

import structlog

from agents.base import parse_json_result, run_agent, scaled_max_tokens
from agents.skeleton_generator.prompt import AGENT_ID, AGENT_NAME, SYSTEM_PROMPT
from agents.stack_specs import STACK_PLAYBOOKS, STACKS, UNIVERSAL_RULES
from agents.tools import SKELETON_GENERATOR_HANDLERS, SKELETON_GENERATOR_TOOL_DEFS
from services import db

logger = structlog.getLogger(__name__)


async def run(question_id: str, output_dir: str, stack: str, difficulty: str, design: dict) -> dict:
    """Write the skeleton under <output_dir>/skeleton/ per the design and playbook."""
    start = time.monotonic()
    log = logger.bind(question_id=question_id, agent=AGENT_ID)
    skeleton_dir = str(Path(output_dir) / "skeleton")

    system_prompt = f"{SYSTEM_PROMPT}\n{UNIVERSAL_RULES}\n{STACK_PLAYBOOKS[stack]}"
    user_message = f"""Generate the skeleton:
question_id:  {question_id}
stack:        {STACKS[stack]}
difficulty:   {difficulty}
skeleton_dir: {skeleton_dir}

Design (implement exactly this, nothing more, nothing less):
{json.dumps({k: v for k, v in design.items() if k != "status"}, indent=2)}

Steps:
1. Write every file from planned_file_tree (except test files — a later agent writes those) using
   write_files(files={{...}}, output_dir="{skeleton_dir}").
2. Call list_files(directory="{skeleton_dir}") to confirm.
3. Respond with ONLY: {{"question_id": "{question_id}", "skeleton_dir": "{skeleton_dir}", "files_written": <count>}}
"""

    result_text, tokens = await run_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        tools=SKELETON_GENERATOR_TOOL_DEFS,
        tool_handlers=SKELETON_GENERATOR_HANDLERS,
        max_tokens=scaled_max_tokens(32000, difficulty),
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
            logs=f"skeleton_dir={skeleton_dir} files_written={result.get('files_written')}",
            duration_seconds=duration,
            tokens_used=tokens,
        )
        log.info("skeleton_done", skeleton_dir=skeleton_dir, tokens=tokens)
        return result
    except json.JSONDecodeError:
        log.error("skeleton_parse_error", result_text=result_text[:500])
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
