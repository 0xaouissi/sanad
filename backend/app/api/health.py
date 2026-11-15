from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app import __version__
from app.core.config import get_settings
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