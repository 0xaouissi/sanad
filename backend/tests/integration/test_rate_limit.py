"""Rate limits through the real chat endpoint (in-memory counters per test)."""

import json

from app.core.config import get_settings
from tests.integration.conftest import auth, create_company


async def _ask(client, api_key, **extra):
    return await client.post(
        "/api/v1/chat", json={"message": "What is the refund policy?", **extra},
        headers=auth(api_key),
    )


async def test_per_ip_429_with_retry_after(client, fake_llm, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "2")
    get_settings.cache_clear()
    company = await create_company(client)
    assert (await _ask(client, company["api_key"])).status_code == 200
    assert (await _ask(client, company["api_key"])).status_code == 200
    blocked = await _ask(client, company["api_key"])
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60
    assert "per IP" in blocked.json()["detail"]
    assert len(fake_llm.calls) == 0  # no documents: refusals, LLM never called


async def test_per_site_limit_shared_across_ips(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "0")
    monkeypatch.setenv("RATE_LIMIT_PER_SITE", "1")
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "true")
    get_settings.cache_clear()
    company = await create_company(client)
    first = await client.post(
        "/api/v1/chat",
        json={"message": "Hello"},
        headers={**auth(company["api_key"]), "X-Forwarded-For": "1.1.1.1"},
    )
    assert first.status_code == 200
    second = await client.post(
        "/api/v1/chat",
        json={"message": "Hello"},
        headers={**auth(company["api_key"]), "X-Forwarded-For": "2.2.2.2"},
    )
    assert second.status_code == 429
    assert "per site" in second.json()["detail"]


async def test_daily_cap_per_company(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "0")
    monkeypatch.setenv("RATE_LIMIT_PER_SITE", "0")
    monkeypatch.setenv("DAILY_CAP_PER_COMPANY", "1")
    get_settings.cache_clear()
    company = await create_company(client)
    assert (await _ask(client, company["api_key"])).status_code == 200
    blocked = await _ask(client, company["api_key"])
    assert blocked.status_code == 429
    assert "chats/day" in blocked.json()["detail"]
    other = await create_company(client, "Other")
    assert (await _ask(client, other["api_key"])).status_code == 200


async def test_zero_disables_limits(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "0")
    monkeypatch.setenv("RATE_LIMIT_PER_SITE", "0")
    monkeypatch.setenv("DAILY_CAP_PER_COMPANY", "0")
    get_settings.cache_clear()
    company = await create_company(client)
    for _ in range(5):
        assert (await _ask(client, company["api_key"])).status_code == 200


async def test_site_key_path_is_limited(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "1")
    get_settings.cache_clear()
    company = await create_company(client)
    response = await client.put(
        "/api/v1/companies/domains",
        json={"domains": ["acme.com"]},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200
    headers = {"X-Site-Key": company["site_key"], "Origin": "https://acme.com"}
    first = await client.post("/api/v1/chat", json={"message": "Hello"}, headers=headers)
    assert first.status_code == 200
    second = await client.post("/api/v1/chat", json={"message": "Hello"}, headers=headers)
    assert second.status_code == 429


async def test_streamed_requests_consume_the_limit(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_IP", "1")
    get_settings.cache_clear()
    company = await create_company(client)
    async with client.stream(
        "POST",
        "/api/v1/chat",
        json={"message": "Hello", "stream": True},
        headers=auth(company["api_key"]),
    ) as response:
        assert response.status_code == 200
        events = [
            json.loads(line[6:])
            async for line in response.aiter_lines()
            if line.startswith("data: ")
        ]
    assert events[-1]["type"] == "done"
    blocked = await _ask(client, company["api_key"])
    assert blocked.status_code == 429