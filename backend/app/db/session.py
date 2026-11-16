from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

log = structlog.get_logger()

_BACKEND_DIR = Path(__file__).resolve().parents[2]


class DatabaseUnavailableError(RuntimeError):
    pass


@lru_cache
def get_engine() -> AsyncEngine:
    # No register_vector here: pgvector's SQLAlchemy type already serializes to
    # the text form asyncpg passes through for the vector OID. Registering the
    # binary codec would reject that string (expects list/ndarray).
    return create_async_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


def _run_migrations(connection) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.attributes["connection"] = connection
    command.upgrade(cfg, "head")


async def init_db() -> None:
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            # The extension needs superuser rights; the README covers creating
            # it once. Migrations assume it exists.
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(_run_migrations)
    except (SQLAlchemyError, OSError) as exc:
        url = get_settings().database_url
        raise DatabaseUnavailableError(
            f"Cannot initialize PostgreSQL ({url}). Is the server running and is "
            "pgvector installed? Start it, or fix DATABASE_URL in .env. "
            f"Details: {exc}"
        ) from exc
    log.info("database_ready")


async def dispose_db() -> None:
    if get_engine.cache_info().currsize:
        await get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()