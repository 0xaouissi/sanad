"""Step 6c acceptance: human handoff over real transports, end to end.

Real Ollama + BGE-M3 + PostgreSQL: upload trilingual documents, ask grounded
questions in Arabic, French and English, then request a human through the
public site-key endpoint. Email lands in a real local SMTP sink (parsed back
into a message), Telegram lands in a local HTTP fixture speaking the Bot API
shape. Verifies storage, the privacy toggle, and the dashboard handoffs list.

Run: HF_HOME=... pytest tests/e2e/test_handoff.py -m e2e (see README).
"""

import email
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.db.models import ChannelStatus, HandoffRequest
from app.db.session import get_session_factory
from app.providers.llm.base import LLMError
from app.providers.llm.ollama import OllamaProvider
from tests.e2e.conftest import ADMIN_KEY, upload_and_wait
from tests.e2e.test_live_chat import GROUNDED_CASES, POLICY_AR, POLICY_EN, POLICY_FR
from tests.e2e.test_widget_browser import smtp_sink  # noqa: F401  (pytest fixture)

VISITOR = "visitor@example.com"
SUPPORT = "support@acme.test"
CHAT_ID = "-100123456"
BOT_TOKEN = "123456:E2E-TEST-TOKEN"


@pytest.fixture(autouse=True)
async def _ollama_up():
    provider = OllamaProvider(Settings())
    try:
        await provider.health()
    except LLMError as exc:
        pytest.skip(f"Live Ollama unavailable: {exc}")


class _TelegramHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length))
        self.server.requests.append({"path": self.path, "payload": payload})
        body = json.dumps({"ok": True, "result": {"message_id": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def telegram_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TelegramHandler)
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture
def handoff_transports(live_rag, monkeypatch, smtp_sink, telegram_server):  # noqa: F811
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", str(smtp_sink.server_address[1]))
    monkeypatch.setenv("SMTP_FROM", "e2e@sanad.test")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    monkeypatch.setenv(
        "TELEGRAM_API_BASE", f"http://127.0.0.1:{telegram_server.server_address[1]}"
    )
    monkeypatch.setenv("HANDOFF_RATE_LIMIT_PER_IP", "0")
    monkeypatch.setenv("HANDOFF_DAILY_CAP_PER_COMPANY", "0")
    # Bot deterrence has dedicated tests; this suite exercises the transport path.
    monkeypatch.setenv("BOT_CHECK_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_handoff_real_transports_trilingual(
    live_rag, handoff_transports, smtp_sink, telegram_server  # noqa: F811
):
    client = live_rag
    suffix = uuid4().hex[:8]
    owner_email = f"owner-{suffix}@acme.test"

    response = await client.post(
        "/api/v1/companies",
        json={
            "name": "Handoff E2E Co",
            "owner_email": owner_email,
            "owner_password": "owner-password-1",
        },
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    assert response.status_code == 201, response.text
    company = response.json()
    api_key = company["api_key"]
    secret = {"X-API-Key": api_key}

    response = await client.put(
        "/api/v1/companies/domains", json={"domains": ["acme.test"]}, headers=secret
    )
    assert response.status_code == 200, response.text

    # Standing rule: upload documents and ask questions in ar/fr/en.
    for filename, text in [
        ("policy-en.md", POLICY_EN),
        ("policy-fr.md", POLICY_FR),
        ("policy-ar.md", POLICY_AR),
    ]:
        await upload_and_wait(client, api_key, filename, text.encode("utf-8"))

    for lang, question in GROUNDED_CASES:
        response = await client.post(
            "/api/v1/chat", json={"message": question, "stream": False}, headers=secret
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["language"] == lang, data
        assert data["answer"], data
        assert data["citations"], data

    # Owner configures both handoff destinations in dashboard Settings.
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": owner_email, "password": "owner-password-1"},
    )
    assert response.status_code == 200, response.text
    csrf = {"X-CSRF-Token": response.json()["csrf_token"]}
    response = await client.put(
        "/api/v1/dashboard/settings",
        json={"handoff_email": SUPPORT, "telegram_chat_id": CHAT_ID},
        headers=csrf,
    )
    assert response.status_code == 200, response.text
    assert response.json()["smtp_configured"] is True
    assert response.json()["telegram_configured"] is True

    # Visitor requests a human in Arabic via the public site key + Origin.
    site = {"X-Site-Key": company["site_key"], "Origin": "https://acme.test"}
    arabic_message = "أريد التحدث إلى موظف من فضلكم"
    response = await client.post(
        "/api/v1/handoff",
        json={"email": VISITOR, "message": arabic_message},
        headers=site,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"email": "sent", "telegram": "sent", "stored": True}

    # The SMTP sink received a real, parseable email.
    assert smtp_sink.messages, "SMTP sink received no message"
    msg = email.message_from_bytes(smtp_sink.messages[-1], policy=email.policy.default)
    assert msg["To"] == SUPPORT
    assert msg["Reply-To"] == VISITOR
    assert msg["From"] == "e2e@sanad.test"
    body = msg.get_content()
    assert arabic_message in body
    assert VISITOR in body

    # The Telegram fixture received a real sendMessage call.
    assert len(telegram_server.requests) == 1
    call = telegram_server.requests[0]
    assert call["path"] == f"/bot{BOT_TOKEN}/sendMessage"
    assert call["payload"]["chat_id"] == CHAT_ID
    assert arabic_message in call["payload"]["text"]
    assert BOT_TOKEN not in json.dumps(call["payload"])

    # Stored with detected language and per-channel statuses.
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(HandoffRequest).where(HandoffRequest.company_id == company["id"])
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].email == VISITOR
    assert rows[0].language == "ar"
    assert rows[0].email_status == ChannelStatus.SENT
    assert rows[0].telegram_status == ChannelStatus.SENT

    # The owner sees it in the dashboard list.
    listed = await client.get("/api/v1/dashboard/handoffs")
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    assert items[0]["email"] == VISITOR
    assert items[0]["email_status"] == "sent"
    assert items[0]["telegram_status"] == "sent"

    # Privacy off: still delivered on both channels, but nothing new is stored.
    response = await client.put(
        "/api/v1/dashboard/settings", json={"store_conversations": False}, headers=csrf
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        "/api/v1/handoff",
        json={"email": VISITOR, "message": "Bonjour, rappelez-moi", "language": "fr"},
        headers=site,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"email": "sent", "telegram": "sent", "stored": False}
    assert len(smtp_sink.messages) == 2
    assert len(telegram_server.requests) == 2
    assert "Bonjour, rappelez-moi" in telegram_server.requests[1]["payload"]["text"]
    async with get_session_factory()() as session:
        count = len(
            (
                await session.execute(
                    select(HandoffRequest).where(HandoffRequest.company_id == company["id"])
                )
            ).scalars().all()
        )
    assert count == 1
    assert len((await client.get("/api/v1/dashboard/handoffs")).json()) == 1


async def test_handoff_without_destinations_is_actionable(live_rag, handoff_transports):
    client = live_rag
    response = await client.post(
        "/api/v1/companies", json={"name": "No Handoff Co"}, headers={"X-Admin-Key": ADMIN_KEY}
    )
    assert response.status_code == 201, response.text
    company = response.json()
    response = await client.put(
        "/api/v1/companies/domains",
        json={"domains": ["acme.test"]},
        headers={"X-API-Key": company["api_key"]},
    )
    assert response.status_code == 200
    response = await client.post(
        "/api/v1/handoff",
        json={"email": VISITOR, "message": "Please call me back"},
        headers={"X-Site-Key": company["site_key"], "Origin": "https://acme.test"},
    )
    assert response.status_code == 409
    assert "Settings" in response.json()["detail"]
    # Nothing was delivered or stored.
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(HandoffRequest).where(HandoffRequest.company_id == company["id"])
            )
        ).scalars().all()
    assert rows == []