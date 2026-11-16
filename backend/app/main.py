import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.chat import router as chat_router
from app.api.v1.companies import router as companies_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.documents import router as documents_router
from app.api.v1.feedback import router as feedback_router
from app.api.v1.handoff import router as handoff_router
from app.api.v1.metrics import router as metrics_router
from app.api.v1.search import router as search_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_db, init_db
from app.providers.embeddings import get_embedding_provider
from app.providers.kv import close_kv, init_kv
from app.providers.llm import get_llm_provider
from app.providers.reranker import get_rerank_provider
from app.services.crawler import resync_loop

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    await init_kv()
    settings = get_settings()
    resync_task = (
        asyncio.create_task(resync_loop()) if settings.crawl_resync_hours > 0 else None
    )
    yield
    if resync_task is not None:
        resync_task.cancel()
        with suppress(asyncio.CancelledError):
            await resync_task
    await get_llm_provider().aclose()
    await get_embedding_provider().aclose()
    reranker = get_rerank_provider()
    if reranker is not None:
        await reranker.aclose()
    await close_kv()
    await dispose_db()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)

    # The widget runs on customer domains: any origin may call the API, but
    # access is gated by X-Site-Key + the company's Origin allowlist (no cookies).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    app.include_router(feedback_router, prefix="/api/v1")
    app.include_router(handoff_router, prefix="/api/v1")
    app.include_router(metrics_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(dashboard_router, prefix="/api/v1")

    widget_path = Path(__file__).parent / "static" / "widget.js"

    @app.get("/widget.js", include_in_schema=False)
    async def widget_script() -> FileResponse:
        return FileResponse(widget_path, media_type="application/javascript")

    # Built dashboard SPA (dashboard/ → npm run build). Absent in source-only
    # checkouts; the API still works without it.
    dashboard_dir = Path(__file__).parent / "static" / "dashboard"
    if dashboard_dir.is_dir():
        app.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")

    return app


app = create_app()