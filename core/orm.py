"""SQLAlchemy ORM models and async session factory for FS_GEN.

Tables are prefixed fsgen_ so this project can share a database with QGen-HE
without colliding. Schema is created by Base.metadata.create_all at startup
(core/database.py) — no migrations.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import TIMESTAMP, Float, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, declarative_base, mapped_column

Base = declarative_base()


class Question(Base):
    """One generated question. Doubles as the dedup ledger (replaces
    generated_questions_log.md): stack | difficulty | domain | entities | rule."""

    __tablename__ = "fsgen_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    tech_stack: Mapped[str] = mapped_column(Text, nullable=False)
    difficulty: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(Text, nullable=True)
    entities: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    core_business_rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'generating'"))
    output_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    problem_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"), default=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_fsgen_questions_question_id", "question_id", unique=True),
    )


class AgentLog(Base):
    __tablename__ = "fsgen_agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(
        Text, ForeignKey("fsgen_questions.question_id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str] = mapped_column(Text, nullable=False)
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    logs: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"), default=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_fsgen_agent_logs_question_id", "question_id"),
    )


class QuestionFile(Base):
    """Manifest row for every generated file (path on disk, not content)."""

    __tablename__ = "fsgen_question_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(
        Text, ForeignKey("fsgen_questions.question_id", ondelete="CASCADE"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    part: Mapped[str] = mapped_column(Text, nullable=False)  # skeleton | solution | root
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=text("now()"), default=datetime.utcnow
    )

    __table_args__ = (
        Index("ix_fsgen_question_files_question_id", "question_id"),
    )


# ---------------------------------------------------------------------------
# Async session factory
# ---------------------------------------------------------------------------

_session_maker: async_sessionmaker[AsyncSession] | None = None


def _get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _session_maker
    if _session_maker is None:
        from core.database import db_manager
        _session_maker = async_sessionmaker(
            db_manager.get_engine(),
            expire_on_commit=False,
        )
    return _session_maker


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager: yields a session, commits on success, rolls back on error."""
    maker = _get_session_maker()
    async with maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
