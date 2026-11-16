"""GET /metrics: admin-protected Prometheus text with counters and DB gauges."""

from app.core.config import get_settings
from tests.integration.conftest import ADMIN_KEY, auth, create_company


async def test_metrics_requires_admin_key(client):
    assert (await client.get("/api/v1/metrics")).status_code == 401
    wrong = await client.get("/api/v1/metrics", headers={"X-Admin-Key": "nope"})
    assert wrong.status_code == 401


async def test_metrics_disabled_without_admin_key(client, monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    get_settings.cache_clear()
    response = await client.get("/api/v1/metrics", headers={"X-Admin-Key": ADMIN_KEY})
    assert response.status_code == 503
    assert "ADMIN_API_KEY" in response.json()["detail"]


async def test_metrics_exposes_counters_and_gauges(client, fake_llm):
    company = await create_company(client)
    fake_llm.answers = ["You have 30 days. [1]"]
    await client.post(
        "/api/v1/chat", json={"message": "What is the refund policy?"},
        headers=auth(company["api_key"]),
    )
    await client.post(
        "/api/v1/chat", json={"message": "What is the refund policy?"},
        headers=auth(company["api_key"]),
    )
    response = await client.get("/api/v1/metrics", headers={"X-Admin-Key": ADMIN_KEY})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "# TYPE sanad_chats_total counter" in body
    assert "sanad_chats_total 2" in body
    assert "sanad_cache_hits_total 1" in body
    assert "sanad_cache_misses_total 1" in body
    assert "# TYPE sanad_companies gauge" in body
    assert "sanad_companies 1" in body
    assert "sanad_conversations 2" in body
    assert "sanad_messages 4" in body


async def test_refusals_are_counted(client):
    company = await create_company(client)  # no documents: always refuses
    await client.post(
        "/api/v1/chat", json={"message": "What is the refund policy?"},
        headers=auth(company["api_key"]),
    )
    response = await client.get("/api/v1/metrics", headers={"X-Admin-Key": ADMIN_KEY})
    assert "sanad_refusals_total 1" in response.text