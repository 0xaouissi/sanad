from collections.abc import AsyncIterator
from functools import lru_cache

import structlog
from sqlalchemy import text
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


async def init_db() -> None:
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
            # create_all skips existing tables; keep the FTS index present on
            # databases created before Step 3.
            await conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_chunks_fts "
                    "ON chunks USING gin (to_tsvector('simple', content))"
                )
            )
            # create_all does not alter existing tables; add the Step 4 columns
            # to databases created earlier (replaced by Alembic in Step 5).
            await conn.execute(
                text("ALTER TABLE companies ADD COLUMN IF NOT EXISTS site_key VARCHAR(64)")
            )
            await conn.execute(
                text(
                    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS "
                    "allowed_domains JSON NOT NULL DEFAULT '[]'"
                )
            )
            await conn.execute(
                text(
                    "UPDATE companies SET site_key = "
                    "'pk-' || replace(gen_random_uuid()::text, '-', '') "
                    "WHERE site_key IS NULL"
                )
            )
            await conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_companies_site_key "
                    "ON companies (site_key)"
                )
            )
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