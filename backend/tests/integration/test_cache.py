"""Answer cache end-to-end through the API, on both memory and Redis backends."""

import asyncio
import json
import os

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.providers.kv import set_kv_store
from app.providers.kv.memory import MemoryKVStore
from app.providers.kv.redis_store import RedisKVStore
from tests.integration.conftest import auth, create_company, get_document, upload

POLICY = (
    "# Refund policy\n"
    "Customers may request a full refund within 30 days of purchase.\n"
)
QUESTION = "How many days do I have to request a refund?"


@pytest.fixture(params=["memory", "redis"])
async def kv_backend(request):
    if request.param == "memory":
        store = MemoryKVStore()
    else:
        url = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")
        store = RedisKVStore(url)
        try:
            await store.ping()
        except (RedisError, OSError) as exc:
            pytest.skip(f"Redis not reachable at {url} ({exc}). Start it or set TEST_REDIS_URL.")
        raw = Redis.from_url(url, protocol=2)
        await raw.flushdb()
        await raw.aclose()
    set_kv_store(store)
    yield store
    await store.aclose()
    set_kv_store(None)


async def _wait_ready(client, api_key, doc_id):
    for _ in range(60):
        doc = await get_document(client, api_key, doc_id)
        if doc["status"] == "ready":
            return
        assert doc["status"] != "failed", doc
        await asyncio.sleep(0.2)
    raise AssertionError("ingestion timed out")


async def _ask(client, api_key, question=QUESTION, **extra):
    response = await client.post(
        "/api/v1/chat", json={"message": question, **extra}, headers=auth(api_key)
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_repeat_question_hits_cache(client, fake_llm, kv_backend):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.md", POLICY.encode())
    await _wait_ready(client, company["api_key"], doc["id"])
    fake_llm.answers = ["You have 30 days. [1]"]
    first = await _ask(client, company["api_key"])
    second = await _ask(client, company["api_key"])
    assert len(fake_llm.calls) == 1
    assert first["answer"] == second["answer"]
    assert first["citations"] == second["citations"]
    assert first["message_id"] != second["message_id"]
    assert first["conversation_id"] != second["conversation_id"]


async def test_cache_never_leaks_between_companies(client, fake_llm, kv_backend):
    a = await create_company(client, "A")
    b = await create_company(client, "B")
    for company in (a, b):
        doc = await upload(client, company["api_key"], "policy.md", POLICY.encode())
        await _wait_ready(client, company["api_key"], doc["id"])
    fake_llm.answers = ["Answer for A. [1]", "Answer for B. [1]"]
    assert (await _ask(client, a["api_key"]))["answer"] == "Answer for A. [1]"
    assert (await _ask(client, b["api_key"]))["answer"] == "Answer for B. [1]"
    assert len(fake_llm.calls) == 2
    # A's cached answer is still A's, not B's.
    assert (await _ask(client, a["api_key"]))["answer"] == "Answer for A. [1]"
    assert len(fake_llm.calls) == 2


async def test_cache_separates_languages(client, fake_llm, kv_backend):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.md", POLICY.encode())
    await _wait_ready(client, company["api_key"], doc["id"])
    fake_llm.answers = ["You have 30 days. [1]", "Vous avez 30 jours. [1]"]
    en = await _ask(client, company["api_key"])
    fr = await _ask(client, company["api_key"], language="fr")
    assert en["language"] == "en"
    assert fr["language"] == "fr"
    assert fr["answer"] == "Vous avez 30 jours. [1]"
    assert len(fake_llm.calls) == 2


async def test_new_document_invalidates_cache(client, fake_llm, kv_backend):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.md", POLICY.encode())
    await _wait_ready(client, company["api_key"], doc["id"])
    fake_llm.answers = ["Old answer. [1]"]
    await _ask(client, company["api_key"])
    other = await upload(
        client, company["api_key"], "extra.md", b"# Extra\nMore content here.\n"
    )
    await _wait_ready(client, company["api_key"], other["id"])
    fake_llm.answers = ["New answer. [1]"]
    assert (await _ask(client, company["api_key"]))["answer"] == "New answer. [1]"
    assert len(fake_llm.calls) == 2


async def test_delete_document_invalidates_cache(client, fake_llm, kv_backend):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.md", POLICY.encode())
    await _wait_ready(client, company["api_key"], doc["id"])
    fake_llm.answers = ["Cached answer. [1]"]
    await _ask(client, company["api_key"])
    response = await client.delete(
        f"/api/v1/documents/{doc['id']}", headers=auth(company["api_key"])
    )
    assert response.status_code == 204
    again = await _ask(client, company["api_key"])
    # No sources left: the refusal is fresh, not the cached answer.
    assert again["answer"].startswith("I don't know")
    assert again["citations"] == []


async def test_followup_with_history_is_not_cached(client, fake_llm, kv_backend):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.md", POLICY.encode())
    await _wait_ready(client, company["api_key"], doc["id"])
    fake_llm.answers = ["First. [1]", "Second. [1]"]
    first = await _ask(client, company["api_key"])
    followup = await _ask(
        client, company["api_key"], conversation_id=first["conversation_id"]
    )
    assert followup["answer"] == "Second. [1]"
    assert len(fake_llm.calls) == 2


async def test_streamed_repeat_hits_cache(client, fake_llm, kv_backend):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.md", POLICY.encode())
    await _wait_ready(client, company["api_key"], doc["id"])
    fake_llm.answers = ["You have 30 days. [1]"]

    async def stream_once():
        events = []
        async with client.stream(
            "POST",
            "/api/v1/chat",
            json={"message": QUESTION, "stream": True},
            headers=auth(company["api_key"]),
        ) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return events

    first = await stream_once()
    second = await stream_once()
    assert len(fake_llm.calls) == 1
    done1 = next(e for e in first if e["type"] == "done")
    done2 = next(e for e in second if e["type"] == "done")
    assert done1["citations"] == done2["citations"]
    text2 = "".join(e["content"] for e in second if e["type"] == "token")
    assert text2 == "You have 30 days. [1]"


async def test_cache_disabled(client, fake_llm, kv_backend, monkeypatch):
    monkeypatch.setenv("CACHE_ENABLED", "false")
    get_settings.cache_clear()
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.md", POLICY.encode())
    await _wait_ready(client, company["api_key"], doc["id"])
    fake_llm.answers = ["Answer. [1]"]
    await _ask(client, company["api_key"])
    await _ask(client, company["api_key"])
    assert len(fake_llm.calls) == 2