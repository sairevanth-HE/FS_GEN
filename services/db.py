"""Async DB tool handlers — thin wrappers over core.repository."""

from __future__ import annotations

from typing import Optional

from core import repository


async def db_create_question(
    question_id: str,
    tech_stack: str,
    difficulty: str,
    domain: Optional[str],
    output_dir: str,
) -> dict:
    return await repository.create_question(question_id, tech_stack, difficulty, domain, output_dir)


async def db_update_question_status(question_id: str, status: str) -> dict:
    return await repository.update_question_status(question_id, status)


async def db_finalize_question(
    question_id: str,
    domain: str,
    entities: list,
    core_business_rule: str,
    problem_statement: str,
    status: str = "complete",
) -> dict:
    return await repository.finalize_question(
        question_id, domain, entities, core_business_rule, problem_statement, status
    )


async def db_get_question(question_id: str) -> Optional[dict]:
    return await repository.get_question(question_id)


async def db_sum_agent_tokens(question_id: str) -> int:
    return await repository.sum_agent_tokens(question_id)


async def db_list_questions(limit: Optional[int] = None) -> list:
    return await repository.list_questions(limit)


async def db_log_agent(
    question_id: str,
    agent_id: str,
    agent_name: str,
    status: str,
    logs: str = "",
    duration_seconds: Optional[float] = None,
    tokens_used: Optional[int] = None,
) -> dict:
    return await repository.log_agent(
        question_id, agent_id, agent_name, status, logs, duration_seconds, tokens_used
    )


async def db_save_file_manifest(question_id: str, files: list) -> dict:
    return await repository.save_file_manifest(question_id, files)


async def db_record_stack_lesson(stack: str, lesson: str) -> None:
    await repository.record_stack_lesson(stack, lesson)


async def db_get_stack_lessons_block(stack: str, limit: int = 8) -> str:
    """Ready-to-append prompt text: past pitfalls for this stack, or "" if none yet."""
    lessons = await repository.get_stack_lessons(stack, limit)
    if not lessons:
        return ""
    bullets = "\n".join(f"- {lesson}" for lesson in lessons)
    return f"\n\n## Known pitfalls from past runs on this stack\n{bullets}\n"
