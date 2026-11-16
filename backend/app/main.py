import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response

from app import __version__
from app.api.health import router as health_router
from app.api.v1.chat import router as chat_router
from app.api.v1.companies import router as companies_router
from app.api.v1.documents import router as documents_router
from app.api.v1.search import router as search_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_db, init_db
from app.providers.embeddings import get_embedding_provider
from app.providers.llm import get_llm_provider
from app.providers.reranker import get_rerank_provider

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield
    await get_llm_provider().aclose()
    await get_embedding_provider().aclose()
    reranker = get_rerank_provider()
    if reranker is not None:
        await reranker.aclose()
    await dispose_db()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)

    @app.middleware("http")
    async def access_log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=uuid4().hex[:12])
        start = time.perf_counter()
        response = await call_next(request)
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return response

    app.include_router(health_router)
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(companies_router, prefix="/api/v1")
    app.include_router(documents_router, prefix="/api/v1")
    app.include_router(search_router, prefix="/api/v1")
    return app


app = create_app()