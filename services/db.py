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
) -> dict:
    return await repository.finalize_question(
        question_id, domain, entities, core_business_rule, problem_statement
    )


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
