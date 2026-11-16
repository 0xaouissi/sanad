"""Company creation and API-key auth against real PostgreSQL."""

from tests.integration.conftest import ADMIN_KEY, auth, create_company


async def test_create_company_returns_key_once(client):
    body = await create_company(client, "Acme Corp")
    assert body["name"] == "Acme Corp"
    assert body["api_key"].startswith("sk-")
    assert body["id"]


async def test_create_without_admin_key_configured(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "admin_api_key", None)
    response = await client.post(
        "/api/v1/companies", json={"name": "X"}, headers={"X-Admin-Key": "anything"}
    )
    assert response.status_code == 503
    assert "ADMIN_API_KEY" in response.json()["detail"]


async def test_create_with_wrong_admin_key(client):
    response = await client.post(
        "/api/v1/companies", json={"name": "X"}, headers={"X-Admin-Key": "wrong"}
    )
    assert response.status_code == 401


async def test_blank_name_rejected(client):
    response = await client.post(
        "/api/v1/companies", json={"name": "   "}, headers={"X-Admin-Key": ADMIN_KEY}
    )
    assert response.status_code == 422


async def test_invalid_api_key_rejected(client):
    response = await client.get("/api/v1/documents", headers=auth("sk-invalid"))
    assert response.status_code == 401
    assert "X-API-Key" in response.json()["detail"]


async def test_missing_api_key_rejected(client):
    response = await client.get("/api/v1/documents")
    assert response.status_code == 401
    assert "X-API-Key" in response.json()["detail"]