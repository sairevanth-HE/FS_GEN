"""A-01: Designer — async run."""

from __future__ import annotations

import json
import time

import structlog

from agents.base import parse_json_result, run_agent, scaled_max_tokens
from agents.designer.prompt import AGENT_ID, AGENT_NAME, SYSTEM_PROMPT
from agents.stack_specs import STACK_PLAYBOOKS, STACKS, UNIVERSAL_RULES
from agents.tools import DESIGNER_HANDLERS, DESIGNER_TOOL_DEFS
from services import db

logger = structlog.getLogger(__name__)


async def run(question_id: str, stack: str, difficulty: str, domain: str, ledger: list[dict]) -> dict:
    """Design the question: entities, API contract, logic-complexity items.

    Returns the design dict (see prompt.py for shape) plus a "status" key.
    """
    start = time.monotonic()
    log = logger.bind(question_id=question_id, agent=AGENT_ID)

    ledger_lines = "\n".join(
        f"- {q['tech_stack']} | {q['difficulty']} | {q['domain']} | "
        f"{json.dumps(q['entities'])} | {q['core_business_rule']}"
        for q in ledger if q.get("domain")
    ) or "(empty — no questions generated yet)"

    system_prompt = f"{SYSTEM_PROMPT}\n{UNIVERSAL_RULES}\n{STACK_PLAYBOOKS[stack]}"
    user_message = f"""Design a question:
stack:      {STACKS[stack]}
difficulty: {difficulty}
domain:     {domain}

Ledger of previously generated questions (stack | difficulty | domain | entities | core rule):
{ledger_lines}
"""

    result_text, tokens = await run_agent(
        system_prompt=system_prompt,
        user_message=user_message,
        tools=DESIGNER_TOOL_DEFS,
        tool_handlers=DESIGNER_HANDLERS,
        max_tokens=scaled_max_tokens(8000, difficulty),
    )

    duration = time.monotonic() - start

    try:
        design = parse_json_result(result_text)
        design["status"] = "done"
        await db.db_log_agent(
            question_id=question_id,
            agent_id=AGENT_ID,
            agent_name=AGENT_NAME,
            status="success",
            logs=f"domain={design.get('domain')} rule={design.get('core_business_rule')}",
            duration_seconds=duration,
            tokens_used=tokens,
        )
        log.info("design_done", domain=design.get("domain"), tokens=tokens)
        return design
    except json.JSONDecodeError:
        log.error("design_parse_error", result_text=result_text[:500])
        await db.db_log_agent(
            question_id=question_id,
            agent_id=AGENT_ID,
            agent_name=AGENT_NAME,
            status="failed",
            logs=result_text,
            duration_seconds=duration,
            tokens_used=tokens,
        )
        return {"status": "failed", "error": result_text}
