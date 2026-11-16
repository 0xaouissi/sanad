"""Dashboard auth: scrypt passwords, cookie sessions, CSRF, login limits, roles."""

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import DashboardUser
from app.db.session import get_session_factory
from app.providers.kv import get_kv_store
from tests.integration.conftest import ADMIN_KEY, create_company

OWNER_EMAIL = "owner@acme.com"
OWNER_PASSWORD = "owner-password-1"


async def create_company_with_owner(
    client, name: str = "Acme", email: str = OWNER_EMAIL, password: str = OWNER_PASSWORD
) -> dict:
    response = await client.post(
        "/api/v1/companies",
        json={"name": name, "owner_email": email, "owner_password": password},
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def login(client, email: str = OWNER_EMAIL, password: str = OWNER_PASSWORD):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_login_sets_httponly_cookie_and_csrf(client) -> None:
    company = await create_company_with_owner(client)
    response = await login(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["email"] == OWNER_EMAIL
    assert body["user"]["role"] == "owner"
    assert body["company"]["id"] == company["id"]
    assert body["csrf_token"]
    cookie = response.headers["set-cookie"]
    assert "sanad_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" not in cookie  # COOKIE_SECURE defaults to false for local dev


async def test_login_email_is_case_insensitive(client) -> None:
    await create_company_with_owner(client)
    response = await login(client, email="Owner@Acme.COM")
    assert response.status_code == 200, response.text


async def test_wrong_password_and_unknown_email_give_same_401(client) -> None:
    await create_company_with_owner(client)
    wrong = await login(client, password="not-the-password")
    unknown = await login(client, email="nobody@acme.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "Invalid email or password."


async def test_passwords_stored_hashed(client) -> None:
    await create_company_with_owner(client)
    async with get_session_factory()() as session:
        user = await session.scalar(select(DashboardUser))
    assert user.password_hash.startswith("scrypt$")
    assert OWNER_PASSWORD not in user.password_hash


async def test_login_rate_limit(client, monkeypatch) -> None:
    await create_company_with_owner(client)
    monkeypatch.setenv("LOGIN_RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    assert (await login(client, password="bad-1")).status_code == 401
    assert (await login(client, password="bad-2")).status_code == 401
    limited = await login(client)
    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1


async def test_me_requires_session(client) -> None:
    await create_company_with_owner(client)
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    await login(client)
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["role"] == "owner"


async def test_expired_session_is_rejected(client) -> None:
    await create_company_with_owner(client)
    await login(client)
    await get_kv_store().delete_prefix("sess:")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_logout_needs_csrf_and_kills_session(client) -> None:
    await create_company_with_owner(client)
    csrf = (await login(client)).json()["csrf_token"]
    assert (await client.post("/api/v1/auth/logout")).status_code == 403
    assert (
        await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": "wrong"})
    ).status_code == 403
    out = await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_add_viewer_requires_owner_and_csrf(client) -> None:
    await create_company_with_owner(client)
    csrf = (await login(client)).json()["csrf_token"]
    payload = {"email": "viewer@acme.com", "password": "viewer-password-1"}
    assert (await client.post("/api/v1/dashboard/users", json=payload)).status_code == 403
    assert (
        await client.post(
            "/api/v1/dashboard/users", json=payload, headers={"X-CSRF-Token": "wrong"}
        )
    ).status_code == 403
    created = await client.post(
        "/api/v1/dashboard/users", json=payload, headers={"X-CSRF-Token": csrf}
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "viewer"
    users = await client.get("/api/v1/dashboard/users")
    assert users.status_code == 200
    assert {u["role"] for u in users.json()} == {"owner", "viewer"}


async def test_viewer_is_read_only(client) -> None:
    await create_company_with_owner(client)
    owner_csrf = (await login(client)).json()["csrf_token"]
    await client.post(
        "/api/v1/dashboard/users",
        json={"email": "viewer@acme.com", "password": "viewer-password-1"},
        headers={"X-CSRF-Token": owner_csrf},
    )
    viewer_login = await login(client, email="viewer@acme.com", password="viewer-password-1")
    assert viewer_login.status_code == 200
    assert viewer_login.json()["user"]["role"] == "viewer"
    viewer_csrf = viewer_login.json()["csrf_token"]
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert (await client.get("/api/v1/dashboard/users")).status_code == 403
    forbidden = await client.post(
        "/api/v1/dashboard/users",
        json={"email": "another@acme.com", "password": "another-password-1"},
        headers={"X-CSRF-Token": viewer_csrf},
    )
    assert forbidden.status_code == 403
    assert "owner role" in forbidden.json()["detail"]


async def test_duplicate_email_rejected(client) -> None:
    await create_company_with_owner(client)
    second = await client.post(
        "/api/v1/companies",
        json={"name": "Other", "owner_email": OWNER_EMAIL, "owner_password": "other-password-1"},
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    assert second.status_code == 409
    csrf = (await login(client)).json()["csrf_token"]
    dup = await client.post(
        "/api/v1/dashboard/users",
        json={"email": OWNER_EMAIL, "password": "viewer-password-1"},
        headers={"X-CSRF-Token": csrf},
    )
    assert dup.status_code == 409


async def test_owner_credentials_must_come_in_pairs(client) -> None:
    response = await client.post(
        "/api/v1/companies",
        json={"name": "Acme", "owner_email": OWNER_EMAIL},
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    assert response.status_code == 422


async def test_company_without_owner_still_works(client) -> None:
    company = await create_company(client)
    assert company["api_key"]
    assert (await login(client)).status_code == 401


async def test_sessions_are_company_scoped(client) -> None:
    acme = await create_company_with_owner(client, name="Acme")
    await create_company_with_owner(client, name="Other", email="owner@other.com")
    await login(client)
    me = await client.get("/api/v1/auth/me")
    assert me.json()["company"]["id"] == acme["id"]
    assert me.json()["company"]["name"] == "Acme"


@pytest.mark.parametrize("password", ["short", "1234567"])
async def test_short_owner_password_rejected(client, password: str) -> None:
    response = await client.post(
        "/api/v1/companies",
        json={"name": "Acme", "owner_email": OWNER_EMAIL, "owner_password": password},
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    assert response.status_code == 422