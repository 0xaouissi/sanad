from httpx import AsyncClient

from tests.conftest import FakeProvider


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "Sanad"
    assert "version" in body


async def test_llm_health_ok(client: AsyncClient) -> None:
    response = await client.get("/health/llm")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["provider"] == "fake"
    assert body["model"] == "fake-model"


async def test_llm_health_down_returns_503(
    client: AsyncClient, fake_provider: FakeProvider
) -> None:
    fake_provider.fail = True
    response = await client.get("/health/llm")
    assert response.status_code == 503
    assert "down" in response.json()["detail"]