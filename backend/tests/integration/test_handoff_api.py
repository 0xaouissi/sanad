"""Handoff API against real PostgreSQL: delivery, privacy, auth, limits, roles.

SMTP and Telegram are captured fakes (the real transports are exercised in
tests/e2e/test_handoff.py against a local SMTP sink and HTTP fixture).
"""

import json
import smtplib
import time
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import ChannelStatus, Company, HandoffRequest
from app.db.session import get_session_factory
from tests.integration.conftest import auth, create_company
from tests.integration.test_dashboard_auth import (
    create_company_with_owner,
    login,
)

pytestmark = pytest.mark.integration

VISITOR = "visitor@example.com"


@pytest.fixture
def handoff_env(client, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.integration.test")
    monkeypatch.setenv("SMTP_FROM", "sanad@sanad.test")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:INTEGRATION-TOKEN")
    monkeypatch.setenv("TELEGRAM_API_BASE", "http://telegram.test")
    monkeypatch.setenv("HANDOFF_RATE_LIMIT_PER_IP", "0")
    monkeypatch.setenv("HANDOFF_DAILY_CAP_PER_COMPANY", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def smtp_outbox(monkeypatch):
    outbox = {"messages": [], "fail": False}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            outbox["host"], outbox["port"] = host, port

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            outbox["starttls"] = True

        def login(self, user, password):
            outbox["login"] = (user, password)

        def send_message(self, msg):
            if outbox["fail"]:
                raise smtplib.SMTPException("relay denied")
            outbox["messages"].append(msg)

    monkeypatch.setattr("app.services.handoff.smtplib.SMTP", FakeSMTP)
    return outbox


@pytest.fixture
def telegram_outbox(monkeypatch):
    outbox = {"requests": [], "status": 200}

    def handler(request: httpx.Request) -> httpx.Response:
        outbox["requests"].append((str(request.url), json.loads(request.content)))
        if outbox["status"] != 200:
            return httpx.Response(outbox["status"], json={"ok": False, "description": "nope"})
        return httpx.Response(200, json={"ok": True, "result": {}})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.services.handoff.httpx.AsyncClient",
        lambda *a, **kw: real_client(*a, transport=transport, **kw),
    )
    return outbox


async def make_handoff_company(
    client,
    *,
    handoff_email="support@acme.test",
    chat_id="123456",
    domains=True,
    store=True,
) -> dict:
    company = await create_company(client)
    if domains:
        response = await client.put(
            "/api/v1/companies/domains",
            json={"domains": ["acme.test"]},
            headers=auth(company["api_key"]),
        )
        assert response.status_code == 200, response.text
    async with get_session_factory()() as session:
        row = await session.get(Company, UUID(company["id"]))
        row.handoff_email = handoff_email
        row.telegram_chat_id = chat_id
        row.store_conversations = store
        await session.commit()
    return company


def site_headers(company: dict, origin: str = "https://acme.test") -> dict:
    return {"X-Site-Key": company["site_key"], "Origin": origin}


async def post_handoff(client, company, **overrides):
    body = {"email": VISITOR, "message": "Please call me back", **overrides}
    return await client.post("/api/v1/handoff", json=body, headers=site_headers(company))


async def handoff_rows(company_id: str) -> list[HandoffRequest]:
    async with get_session_factory()() as session:
        return list(
            await session.scalars(
                select(HandoffRequest).where(HandoffRequest.company_id == UUID(company_id))
            )
        )


async def test_handoff_delivers_both_channels_and_stores(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    company = await make_handoff_company(client)
    response = await post_handoff(client, company, message="Line one\nLine two")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"email": "sent", "telegram": "sent", "stored": True}

    msg = smtp_outbox["messages"][0]
    assert msg["To"] == "support@acme.test"
    assert msg["Reply-To"] == VISITOR
    assert msg["From"] == "sanad@sanad.test"
    content = msg.get_content()
    assert "Line one" in content and "Line two" in content
    assert VISITOR in content

    url, payload = telegram_outbox["requests"][0]
    assert url == "http://telegram.test/bot123:INTEGRATION-TOKEN/sendMessage"
    assert payload["chat_id"] == "123456"
    assert "Please call me back" not in payload["text"]  # overridden message
    assert "Line one" in payload["text"]

    rows = await handoff_rows(company["id"])
    assert len(rows) == 1
    assert rows[0].email == VISITOR
    assert rows[0].email_status is ChannelStatus.SENT
    assert rows[0].telegram_status is ChannelStatus.SENT
    assert rows[0].language == "en"
    assert rows[0].error is None


async def test_handoff_with_secret_api_key_needs_no_origin(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    company = await make_handoff_company(client)
    response = await client.post(
        "/api/v1/handoff",
        json={"email": VISITOR, "message": "hi"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200, response.text


async def test_handoff_privacy_toggle_off_sends_without_storing(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    company = await make_handoff_company(client, store=False)
    response = await post_handoff(client, company)
    assert response.status_code == 200, response.text
    assert response.json()["stored"] is False
    assert len(smtp_outbox["messages"]) == 1
    assert len(telegram_outbox["requests"]) == 1
    assert await handoff_rows(company["id"]) == []


async def test_handoff_single_channel_skips_the_other(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    company = await make_handoff_company(client, chat_id=None)
    body = (await post_handoff(client, company)).json()
    assert body == {"email": "sent", "telegram": "skipped", "stored": True}
    assert telegram_outbox["requests"] == []

    company = await make_handoff_company(client, handoff_email=None)
    body = (await post_handoff(client, company)).json()
    assert body == {"email": "skipped", "telegram": "sent", "stored": True}
    assert len(smtp_outbox["messages"]) == 1  # only the first company's email


async def test_handoff_not_configured_is_actionable(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    company = await make_handoff_company(client, handoff_email=None, chat_id=None)
    response = await post_handoff(client, company)
    assert response.status_code == 409
    assert "Settings" in response.json()["detail"]
    assert await handoff_rows(company["id"]) == []


async def test_handoff_missing_server_transport_is_actionable(
    client, handoff_env, monkeypatch, smtp_outbox, telegram_outbox
):
    company = await make_handoff_company(client)
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("SMTP_FROM", "")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    get_settings.cache_clear()
    response = await post_handoff(client, company)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "SMTP_HOST" in detail and "TELEGRAM_BOT_TOKEN" in detail


@pytest.mark.parametrize(
    "email",
    ["not-an-email", "visitor@example", "visitor@example.com\r\nBcc: evil@attacker.test"],
)
async def test_handoff_rejects_bad_emails(
    client, handoff_env, smtp_outbox, telegram_outbox, email
):
    company = await make_handoff_company(client)
    response = await post_handoff(client, company, email=email)
    assert response.status_code == 422
    assert smtp_outbox["messages"] == []
    assert await handoff_rows(company["id"]) == []


async def test_handoff_rejects_blank_message(client, handoff_env, smtp_outbox, telegram_outbox):
    company = await make_handoff_company(client)
    response = await post_handoff(client, company, message="   ")
    assert response.status_code == 422


async def test_handoff_auth_and_domain_checks(client, handoff_env, smtp_outbox, telegram_outbox):
    company = await make_handoff_company(client)
    body = {"email": VISITOR, "message": "hi"}
    assert (await client.post("/api/v1/handoff", json=body)).status_code == 401
    assert (
        await client.post("/api/v1/handoff", json=body, headers={"X-Site-Key": "pk-bad"})
    ).status_code == 401
    assert (
        await client.post(
            "/api/v1/handoff", json=body, headers={"X-Site-Key": company["site_key"]}
        )
    ).status_code == 403
    assert (
        await client.post("/api/v1/handoff", json=body, headers=site_headers(company, "https://evil.test"))
    ).status_code == 403
    assert smtp_outbox["messages"] == []

    no_domains = await make_handoff_company(client, domains=False)
    assert (
        await client.post("/api/v1/handoff", json=body, headers=site_headers(no_domains))
    ).status_code == 403


async def test_handoff_bot_check_on_site_key_path(
    client, handoff_env, monkeypatch, smtp_outbox, telegram_outbox
):
    monkeypatch.setenv("BOT_CHECK_ENABLED", "true")
    get_settings.cache_clear()
    company = await make_handoff_company(client)
    base = {"email": VISITOR, "message": "hi"}
    filled = await client.post(
        "/api/v1/handoff",
        json={**base, "website": "spam", "opened_at": time.time() * 1000 - 10_000},
        headers=site_headers(company),
    )
    assert filled.status_code == 400
    missing = await client.post(
        "/api/v1/handoff", json=base, headers=site_headers(company)
    )
    assert missing.status_code == 400
    too_fast = await client.post(
        "/api/v1/handoff",
        json={**base, "opened_at": time.time() * 1000},
        headers=site_headers(company),
    )
    assert too_fast.status_code == 429
    ok = await client.post(
        "/api/v1/handoff",
        json={**base, "opened_at": time.time() * 1000 - 10_000},
        headers=site_headers(company),
    )
    assert ok.status_code == 200, ok.text
    # The secret-key path is exempt from the bot check.
    secret = await client.post("/api/v1/handoff", json=base, headers=auth(company["api_key"]))
    assert secret.status_code == 200


async def test_handoff_rate_limit_per_ip(
    client, handoff_env, monkeypatch, smtp_outbox, telegram_outbox
):
    monkeypatch.setenv("HANDOFF_RATE_LIMIT_PER_IP", "2")
    get_settings.cache_clear()
    company = await make_handoff_company(client)
    assert (await post_handoff(client, company)).status_code == 200
    assert (await post_handoff(client, company)).status_code == 200
    blocked = await post_handoff(client, company)
    assert blocked.status_code == 429
    assert "per IP" in blocked.json()["detail"]
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60


async def test_handoff_daily_cap_per_company(
    client, handoff_env, monkeypatch, smtp_outbox, telegram_outbox
):
    monkeypatch.setenv("HANDOFF_DAILY_CAP_PER_COMPANY", "1")
    get_settings.cache_clear()
    company = await make_handoff_company(client)
    assert (await post_handoff(client, company)).status_code == 200
    blocked = await client.post(
        "/api/v1/handoff",
        json={"email": VISITOR, "message": "hi"},
        headers=auth(company["api_key"]),
    )
    assert blocked.status_code == 429
    assert "requests/day" in blocked.json()["detail"]


async def test_handoff_smtp_failure_still_delivers_telegram(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    smtp_outbox["fail"] = True
    company = await make_handoff_company(client)
    response = await post_handoff(client, company)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "failed" and body["telegram"] == "sent"
    rows = await handoff_rows(company["id"])
    assert rows[0].email_status is ChannelStatus.FAILED
    assert "Could not send" in rows[0].error


async def test_handoff_telegram_failure_still_delivers_email(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    telegram_outbox["status"] = 401
    company = await make_handoff_company(client)
    response = await post_handoff(client, company)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "sent" and body["telegram"] == "failed"
    assert "123:INTEGRATION-TOKEN" not in response.text


async def test_handoff_all_channels_fail_returns_502_and_records(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    smtp_outbox["fail"] = True
    telegram_outbox["status"] = 500
    company = await make_handoff_company(client)
    response = await post_handoff(client, company)
    assert response.status_code == 502
    assert "Could not deliver" in response.json()["detail"]
    rows = await handoff_rows(company["id"])
    assert rows[0].email_status is ChannelStatus.FAILED
    assert rows[0].telegram_status is ChannelStatus.FAILED


async def test_handoff_language_detection_and_override(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    company = await make_handoff_company(client)
    response = await post_handoff(client, company, message="أريد التحدث إلى موظف من فضلكم")
    assert response.status_code == 200, response.text
    response = await post_handoff(client, company, message="Bonjour, rappelez-moi", language="fr")
    assert response.status_code == 200, response.text
    rows = await handoff_rows(company["id"])
    assert sorted(r.language for r in rows) == ["ar", "fr"]


async def test_dashboard_handoffs_list_roles_and_isolation(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    company = await create_company_with_owner(client)
    async with get_session_factory()() as session:
        row = await session.get(Company, UUID(company["id"]))
        row.handoff_email = "support@acme.test"
        row.allowed_domains = ["acme.test"]
        await session.commit()
    assert (await post_handoff(client, company)).status_code == 200

    owner = await login(client)
    assert owner.status_code == 200
    listed = await client.get("/api/v1/dashboard/handoffs")
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["email"] == VISITOR
    assert items[0]["email_status"] == "sent"
    assert items[0]["telegram_status"] == "skipped"

    # Another company's owner sees nothing.
    other = await create_company_with_owner(client, name="Other", email="other@acme.test")
    await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": owner.json()["csrf_token"]})
    other_login = await login(client, email="other@acme.test")
    assert other_login.status_code == 200
    assert (await client.get("/api/v1/dashboard/handoffs")).json() == []
    assert other["id"] != company["id"]

    # Unauthenticated is rejected.
    await client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": other_login.json()["csrf_token"]}
    )
    assert (await client.get("/api/v1/dashboard/handoffs")).status_code == 401


async def test_dashboard_handoffs_visible_to_viewer(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    company = await create_company_with_owner(client)
    async with get_session_factory()() as session:
        row = await session.get(Company, UUID(company["id"]))
        row.handoff_email = "support@acme.test"
        row.allowed_domains = ["acme.test"]
        await session.commit()
    assert (await post_handoff(client, company)).status_code == 200
    owner = await login(client)
    csrf = {"X-CSRF-Token": owner.json()["csrf_token"]}
    added = await client.post(
        "/api/v1/dashboard/users",
        json={"email": "viewer@acme.test", "password": "viewer-password-1"},
        headers=csrf,
    )
    assert added.status_code == 201, added.text
    await client.post("/api/v1/auth/logout", headers=csrf)
    viewer = await login(client, email="viewer@acme.test", password="viewer-password-1")
    assert viewer.status_code == 200
    listed = await client.get("/api/v1/dashboard/handoffs")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_settings_handoff_fields_owner_only(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    await create_company_with_owner(client)
    owner = await login(client)
    csrf = {"X-CSRF-Token": owner.json()["csrf_token"]}
    settings = (await client.get("/api/v1/dashboard/settings")).json()
    assert settings["handoff_email"] is None
    assert settings["telegram_chat_id"] is None
    assert settings["smtp_configured"] is True
    assert settings["telegram_configured"] is True

    updated = await client.put(
        "/api/v1/dashboard/settings",
        json={"handoff_email": "help@acme.test", "telegram_chat_id": "-100123456"},
        headers=csrf,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["handoff_email"] == "help@acme.test"
    assert updated.json()["telegram_chat_id"] == "-100123456"

    cleared = await client.put(
        "/api/v1/dashboard/settings",
        json={"handoff_email": "", "telegram_chat_id": ""},
        headers=csrf,
    )
    assert cleared.json()["handoff_email"] is None
    assert cleared.json()["telegram_chat_id"] is None

    bad = await client.put(
        "/api/v1/dashboard/settings",
        json={"handoff_email": "help@acme.test\r\nBcc: evil@x.test"},
        headers=csrf,
    )
    assert bad.status_code == 422
    bad = await client.put(
        "/api/v1/dashboard/settings", json={"telegram_chat_id": "not a chat"}, headers=csrf
    )
    assert bad.status_code == 422
    no_csrf = await client.put(
        "/api/v1/dashboard/settings", json={"handoff_email": "help@acme.test"}
    )
    assert no_csrf.status_code == 403


async def test_settings_handoff_viewer_read_only(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    await create_company_with_owner(client)
    owner = await login(client)
    csrf = {"X-CSRF-Token": owner.json()["csrf_token"]}
    added = await client.post(
        "/api/v1/dashboard/users",
        json={"email": "viewer@acme.test", "password": "viewer-password-1"},
        headers=csrf,
    )
    assert added.status_code == 201
    await client.post("/api/v1/auth/logout", headers=csrf)
    viewer = await login(client, email="viewer@acme.test", password="viewer-password-1")
    viewer_csrf = {"X-CSRF-Token": viewer.json()["csrf_token"]}
    assert (await client.get("/api/v1/dashboard/settings")).status_code == 200
    blocked = await client.put(
        "/api/v1/dashboard/settings", json={"handoff_email": "help@acme.test"}, headers=viewer_csrf
    )
    assert blocked.status_code == 403


async def test_export_includes_handoff_requests(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    company = await create_company_with_owner(client)
    async with get_session_factory()() as session:
        row = await session.get(Company, UUID(company["id"]))
        row.handoff_email = "support@acme.test"
        row.allowed_domains = ["acme.test"]
        await session.commit()
    assert (await post_handoff(client, company)).status_code == 200
    owner = await login(client)
    assert owner.status_code == 200
    export = await client.get("/api/v1/dashboard/export")
    assert export.status_code == 200
    payload = export.json()
    assert payload["company"]["handoff_email"] == "support@acme.test"
    assert len(payload["handoff_requests"]) == 1
    assert payload["handoff_requests"][0]["email"] == VISITOR
    assert payload["handoff_requests"][0]["message"] == "Please call me back"


async def test_handoff_count_isolated_per_company(
    client, handoff_env, smtp_outbox, telegram_outbox
):
    first = await make_handoff_company(client)
    second = await make_handoff_company(client)
    assert (await post_handoff(client, first)).status_code == 200
    assert (await post_handoff(client, second)).status_code == 200
    assert len(await handoff_rows(first["id"])) == 1
    assert len(await handoff_rows(second["id"])) == 1
    async with get_session_factory()() as session:
        total = await session.scalar(select(func.count()).select_from(HandoffRequest))
    assert total == 2