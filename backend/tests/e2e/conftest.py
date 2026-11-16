"""E2E fixtures: real PostgreSQL + real local BGE-M3 embeddings."""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient
from pytest import MonkeyPatch
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import dispose_db, get_session_factory, init_db
from app.main import create_app
from app.providers.embeddings import get_embedding_provider
from app.providers.llm import get_llm_provider

ADMIN_KEY = "e2e-admin-key"


def pytest_collection_modifyitems(config, items):
    here = Path(__file__).parent
    for item in items:
        if item.path.is_relative_to(here):
            item.add_marker(pytest.mark.e2e)

# Captured at import time, before the autouse clean_env fixture strips them.
_TESSERACT_CMD = os.environ.get("TESSERACT_CMD", "")
_TESSDATA_PREFIX = os.environ.get("TESSDATA_PREFIX", "")
_HF_HOME = os.environ.get("HF_HOME", "")


@pytest.fixture
async def live_rag(monkeypatch: MonkeyPatch, tmp_path) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(
        "DATABASE_URL",
        os.environ.get(
            "TEST_DATABASE_URL", "postgresql+asyncpg://sanad:sanad@localhost:5432/sanad"
        ),
    )
    if _TESSERACT_CMD:
        monkeypatch.setenv("TESSERACT_CMD", _TESSERACT_CMD)
    if _TESSDATA_PREFIX:
        monkeypatch.setenv("TESSDATA_PREFIX", _TESSDATA_PREFIX)
    if _HF_HOME:
        # Must be in os.environ before huggingface_hub is first imported.
        monkeypatch.setenv("HF_HOME", _HF_HOME)
    get_settings.cache_clear()
    get_embedding_provider.cache_clear()
    get_llm_provider.cache_clear()

    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = await asyncpg.connect(dsn, timeout=5)
        await conn.close()
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL not reachable ({exc}). Start it and set DATABASE_URL.")

    from huggingface_hub import try_to_load_from_cache

    cached = try_to_load_from_cache(settings.embedding_model, "pytorch_model.bin")
    if not isinstance(cached, str):
        pytest.skip(
            "BGE-M3 weights not downloaded. Run: huggingface-cli download BAAI/bge-m3"
        )

    await init_db()
    async with get_session_factory()() as session:
        await session.execute(text("TRUNCATE companies CASCADE"))
        await session.commit()

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", timeout=300.0
    ) as client:
        yield client

    await get_embedding_provider().aclose()
    await dispose_db()
    get_settings.cache_clear()
    get_embedding_provider.cache_clear()
    get_llm_provider.cache_clear()


async def make_company(client: AsyncClient, name: str = "E2E Co") -> dict:
    response = await client.post(
        "/api/v1/companies", json={"name": name}, headers={"X-Admin-Key": ADMIN_KEY}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def upload_and_wait(client: AsyncClient, api_key: str, filename: str, data: bytes) -> dict:
    response = await client.post(
        "/api/v1/documents",
        files={"file": (filename, data)},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 202, response.text
    doc = response.json()
    listing = await client.get("/api/v1/documents", headers={"X-API-Key": api_key})
    final = next(d for d in listing.json() if d["id"] == doc["id"])
    assert final["status"] == "ready", final["error"]
    return final


async def search(client: AsyncClient, api_key: str, query: str, top_k: int = 3) -> list[dict]:
    response = await client.post(
        "/api/v1/search",
        json={"query": query, "top_k": top_k},
        headers={"X-API-Key": api_key},
    )
    assert response.status_code == 200, response.text
    return response.json()["hits"]