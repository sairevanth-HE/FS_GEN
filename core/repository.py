"""Async CRUD repository — single source of truth for all DB operations."""

from __future__ import annotations

from datetime import datetime

import structlog
from sqlalchemy import select

from core.orm import AgentLog, Question, QuestionFile, get_session

logger = structlog.getLogger(__name__)


async def create_question(
    question_id: str,
    tech_stack: str,
    difficulty: str,
    domain: str | None,
    output_dir: str,
) -> dict:
    async with get_session() as session:
        q = Question(
            question_id=question_id,
            tech_stack=tech_stack,
            difficulty=difficulty,
            domain=domain,
            output_dir=output_dir,
            status="generating",
        )
        session.add(q)
    return {"question_id": question_id, "status": "generating"}


async def update_question_status(question_id: str, status: str) -> dict:
    async with get_session() as session:
        result = await session.execute(
            select(Question).where(Question.question_id == question_id)
        )
        q = result.scalar_one_or_none()
        if q:
            q.status = status
            q.updated_at = datetime.utcnow()
    return {"question_id": question_id, "status": status}


async def finalize_question(
    question_id: str,
    domain: str,
    entities: list,
    core_business_rule: str,
    problem_statement: str,
) -> dict:
    """Record the ledger fields + problem statement and mark the question complete."""
    async with get_session() as session:
        result = await session.execute(
            select(Question).where(Question.question_id == question_id)
        )
        q = result.scalar_one_or_none()
        if q:
            q.domain = domain
            q.entities = entities
            q.core_business_rule = core_business_rule
            q.problem_statement = problem_statement
            q.status = "complete"
            q.updated_at = datetime.utcnow()
    return {"question_id": question_id, "status": "complete"}


async def list_questions(limit: int | None = None) -> list[dict]:
    """Return the ledger: every question's stack/difficulty/domain/entities/rule."""
    async with get_session() as session:
        stmt = select(Question).order_by(Question.created_at.desc())
        if limit:
            stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        return [
            {
                "question_id": q.question_id,
                "tech_stack": q.tech_stack,
                "difficulty": q.difficulty,
                "domain": q.domain,
                "entities": q.entities,
                "core_business_rule": q.core_business_rule,
                "status": q.status,
                "output_dir": q.output_dir,
                "created_at": str(q.created_at),
            }
            for q in result.scalars().all()
        ]


async def log_agent(
    question_id: str,
    agent_id: str,
    agent_name: str,
    status: str,
    logs: str = "",
    duration_seconds: float | None = None,
    tokens_used: int | None = None,
) -> dict:
    async with get_session() as session:
        session.add(AgentLog(
            question_id=question_id,
            agent_id=agent_id,
            agent_name=agent_name,
            status=status,
            logs=logs or None,
            duration_seconds=duration_seconds,
            tokens_used=tokens_used,
        ))
    return {"question_id": question_id, "agent_id": agent_id, "status": status}


async def save_file_manifest(question_id: str, files: list[dict]) -> dict:
    """files: [{"relative_path": str, "part": "skeleton"|"solution"|"root"}, ...]"""
    async with get_session() as session:
        for f in files:
            session.add(QuestionFile(
                question_id=question_id,
                relative_path=f["relative_path"],
                part=f["part"],
            ))
    return {"question_id": question_id, "files_logged": len(files)}
