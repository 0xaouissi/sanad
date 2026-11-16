from collections.abc import AsyncIterator
from functools import lru_cache

import structlog
from pgvector.asyncpg import register_vector
from sqlalchemy import event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.db.models import Base

log = structlog.get_logger()


class DatabaseUnavailableError(RuntimeError):
    pass


@lru_cache
def get_engine() -> AsyncEngine:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _register_vector(dbapi_connection, _connection_record) -> None:
        dbapi_connection.run_async(register_vector)

    return engine


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


async def init_db() -> None:
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
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