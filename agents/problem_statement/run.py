"""A-05: Problem Statement Writer — async run."""

from __future__ import annotations

import json
import time
from pathlib import Path

import structlog

from agents.base import parse_json_result, run_agent, scaled_max_tokens
from agents.problem_statement.prompt import AGENT_ID, AGENT_NAME, SYSTEM_PROMPT
from agents.stack_specs import PROBLEM_STATEMENT_FORMAT, STACK_PLAYBOOKS, STACKS, UNIVERSAL_RULES
from agents.tools import PROBLEM_STATEMENT_HANDLERS, PROBLEM_STATEMENT_TOOL_DEFS
from services import db

logger = structlog.getLogger(__name__)


async def run(question_id: str, output_dir: str, stack: str, difficulty: str, design: dict) -> dict:
    """Write <output_dir>/problem_statement.md from the skeleton's actual contents."""
    start = time.monotonic()
    log = logger.bind(question_id=question_id, agent=AGENT_ID)
    skeleton_dir = str(Path(output_dir) / "skeleton")

    system_prompt = (
        f"{SYSTEM_PROMPT}\n{PROBLEM_STATEMENT_FORMAT}\n{UNIVERSAL_RULES}\n{STACK_PLAYBOOKS[stack]}"
    )
    user_message = f"""Write the problem statement:
question_id:  {question_id}
stack:        {STACKS[stack]}
difficulty:   {difficulty}
skeleton_dir: {skeleton_dir}
write the file to: {output_dir}  (as problem_statement.md)

Design (for background/domain context only — the skeleton on disk is the source of truth):
{json.dumps({k: v for k, v in design.items() if k != "status"}, indent=2)}

Steps:
1. list_files(directory="{skeleton_dir}") and read_file every stubbed file (and the infra files
   needed for the Data model and Ports sections).
2. write_files(files={{"problem_statement.md": "..."}}, output_dir="{output_dir}").
3. Respond with ONLY: {{"question_id": "{question_id}", "title": "...", "path": "{output_dir}/problem_statement.md"}}
"""

    result_text, tokens = await run_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        tools=PROBLEM_STATEMENT_TOOL_DEFS,
        tool_handlers=PROBLEM_STATEMENT_HANDLERS,
        max_tokens=scaled_max_tokens(12000, difficulty),
        tier="cheap",  # prose write-up of an already-decided design — brush-up work
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
            logs=f"title={result.get('title')}",
            duration_seconds=duration,
            tokens_used=tokens,
        )
        log.info("problem_statement_done", title=result.get("title"), tokens=tokens)
        return result
    except json.JSONDecodeError:
        log.error("problem_statement_parse_error", result_text=result_text[:500])
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
