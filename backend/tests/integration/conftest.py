"""Shared fixtures for integration tests: real PostgreSQL + pgvector, fake embeddings."""

import hashlib
import math
import os
import re
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
from app.providers.embeddings.base import EmbeddingProvider
from app.providers.llm import get_llm_provider

ADMIN_KEY = "test-admin-key"


def pytest_collection_modifyitems(config, items):
    here = Path(__file__).parent
    for item in items:
        if item.path.is_relative_to(here):
            item.add_marker(pytest.mark.integration)


class FakeEmbedder(EmbeddingProvider):
    """Deterministic bag-of-words hashing: texts sharing words score higher."""

    name = "fake"
    model = "fake-embeddings"
    dim = 1024

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(word.encode("utf-8")).hexdigest()
            vec[int(digest, 16) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def aclose(self) -> None:
        pass


@pytest.fixture
async def db_ready(monkeypatch: MonkeyPatch, tmp_path) -> AsyncIterator[None]:
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(
        "DATABASE_URL",
        os.environ.get(
            "TEST_DATABASE_URL", "postgresql+asyncpg://sanad:sanad@localhost:5432/sanad"
        ),
    )
    get_settings.cache_clear()
    settings = get_settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    try:
        conn = await asyncpg.connect(dsn, timeout=5)
        await conn.close()
    except (OSError, asyncpg.PostgresError) as exc:
        pytest.skip(f"PostgreSQL not reachable at {dsn} ({exc}). Start it and set DATABASE_URL.")
    await init_db()
    async with get_session_factory()() as session:
        await session.execute(text("TRUNCATE companies CASCADE"))
        await session.commit()
    yield
    await dispose_db()
    get_settings.cache_clear()
    get_embedding_provider.cache_clear()
    get_llm_provider.cache_clear()


@pytest.fixture
async def client(db_ready, monkeypatch: MonkeyPatch) -> AsyncIterator[AsyncClient]:
    fake = FakeEmbedder()
    monkeypatch.setattr("app.services.ingestion.get_embedding_provider", lambda: fake)
    app = create_app()
    app.dependency_overrides[get_embedding_provider] = lambda: fake
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as test_client:
        yield test_client


async def create_company(client: AsyncClient, name: str = "Acme") -> dict:
    response = await client.post(
        "/api/v1/companies", json={"name": name}, headers={"X-Admin-Key": ADMIN_KEY}
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


async def upload(client: AsyncClient, api_key: str, filename: str, data: bytes) -> dict:
    response = await client.post(
        "/api/v1/documents",
        files={"file": (filename, data)},
        headers=auth(api_key),
    )
    assert response.status_code == 202, response.text
    return response.json()


async def get_document(client: AsyncClient, api_key: str, document_id: str) -> dict:
    response = await client.get("/api/v1/documents", headers=auth(api_key))
    assert response.status_code == 200
    return next(d for d in response.json() if d["id"] == document_id)