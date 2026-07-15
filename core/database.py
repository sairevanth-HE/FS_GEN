"""Database manager. Schema is managed by Alembic — run `alembic upgrade head`."""

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core.config import settings

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """Manages database connections"""

    def __init__(self) -> None:
        self.engine: AsyncEngine | None = None
        self._database_url = settings.DATABASE_URL.replace(
            "postgresql://", "postgresql+psycopg://"
        )

    async def initialize(self) -> None:
        """Initialize database connection"""
        self.engine = create_async_engine(self._database_url)
        logger.info("Database initialized")

    async def close(self) -> None:
        """Close database connection"""
        if self.engine:
            await self.engine.dispose()
        logger.info("Database connection closed")

    def get_engine(self) -> AsyncEngine:
        """Get the SQLAlchemy engine"""
        if not self.engine:
            raise RuntimeError("Database not initialized")
        return self.engine


# Global database manager instance
db_manager = DatabaseManager()
