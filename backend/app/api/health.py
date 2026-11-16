from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.providers.llm import get_llm_provider
from app.providers.llm.base import LLMError, LLMProvider

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "app": settings.app_name, "version": __version__}


@router.get("/health/llm")
async def llm_health(
    provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> dict[str, str]:
    try:
        await provider.health()
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"status": "ok", "provider": provider.name, "model": provider.model}


@router.get("/health/db")
async def db_health() -> dict[str, str]:
    try:
        async with get_session_factory()() as session:
            await session.execute(text("SELECT 1"))
            installed = await session.scalar(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            )
    except (SQLAlchemyError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"PostgreSQL unreachable. Start it or fix DATABASE_URL in .env. ({exc})",
        ) from exc
    if not installed:
        raise HTTPException(
            status_code=503,
            detail="pgvector extension missing. Run: CREATE EXTENSION vector; "
            "(install pgvector for your PostgreSQL version first).",
        )
    return {"status": "ok", "pgvector": "installed"}