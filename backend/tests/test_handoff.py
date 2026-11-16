"""Human handoff (Step 6c): validation, header-injection guards, SMTP and
Telegram delivery, channel planning, privacy-respecting persistence, limits."""

import json
import smtplib
import uuid

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import clean_header_text, validate_chat_id, validate_handoff_email
from app.db.models import ChannelStatus, Company, HandoffRequest
from app.providers.kv.memory import MemoryKVStore
from app.schemas.dashboard import SettingsUpdate
from app.schemas.handoff import HandoffRequestIn
from app.services.handoff import (
    HandoffError,
    build_email,
    plan_channels,
    request_handoff,
    send_email,
    send_telegram,
    telegram_text,
)
from app.services.rate_limit import enforce_handoff_limits
from tests.test_rate_limit import BrokenKV, make_request

COMPANY_ID = uuid.uuid4()


def make_company(**overrides) -> Company:
    base = {
        "id": COMPANY_ID,
        "name": "Acme",
        "handoff_email": "support@acme.test",
        "telegram_chat_id": "123456",
        "store_conversations": True,
    }
    return Company(**{**base, **overrides})


def handoff_settings(**overrides) -> Settings:
    base = {
        "smtp_host": "smtp.test",
        "smtp_from": "sanad@sanad.test",
        "smtp_user": "",
        "smtp_password": "",
        "telegram_bot_token": "123:TEST-TOKEN",
        "handoff_rate_limit_per_ip": 0,
        "handoff_daily_cap_per_company": 0,
    }
    return Settings(**{**base, **overrides})


# --- email validation + header injection -------------------------------------


@pytest.mark.parametrize(
    "email",
    [
        "visitor@example.com",
        "first.last+tag@sub.example.co.uk",
        "o'brien@example.ie",
        "a@b.co",
        "  visitor@example.com  ",
    ],
)
def test_valid_emails(email):
    assert validate_handoff_email(email) == email.strip()


@pytest.mark.parametrize(
    "email",
    [
        "",
        "plainaddress",
        "@example.com",
        "visitor@",
        "visitor@example",
        "visitor@localhost",
        "two@@example.com",
        "visitor name@example.com",
        "visitor@exa mple.com",
        "visitor@example.com@",
        "<script>@example.com",
        "visitor@-example.com",
        "visitor@example-.com",
    ],
)
def test_invalid_emails(email):
    with pytest.raises(ValueError, match="valid address"):
        validate_handoff_email(email)


@pytest.mark.parametrize(
    "payload",
    [
        "visitor@example.com\r\nBcc: evil@attacker.test",
        "visitor@example.com\nBcc: evil@attacker.test",
        "visitor@example.com\rBcc: evil@attacker.test",
        "visitor@example.com\r\n",
        "visitor@example.com\x00",
        "visitor\u2028@example.com",
        "visitor@example.com\u2029",
        "\r\nvisitor@example.com",
    ],
)
def test_header_injection_rejected(payload):
    with pytest.raises(ValueError, match="control characters"):
        validate_handoff_email(payload)


def test_email_length_limits():
    with pytest.raises(ValueError, match="too long"):
        validate_handoff_email("a" * 65 + "@example.com")
    with pytest.raises(ValueError, match="too long"):
        validate_handoff_email("a" * 320 + "@example.com")
    assert validate_handoff_email("a" * 64 + "@example.com")


def test_clean_header_text():
    assert clean_header_text("Acme\r\nBcc: evil@x.test") == "AcmeBcc: evil@x.test"
    assert clean_header_text("سند\x00") == "سند"
    assert clean_header_text("Acme Corp") == "Acme Corp"


@pytest.mark.parametrize("chat_id", ["123456789", "-1001234567890", "@acme_support"])
def test_valid_chat_ids(chat_id):
    assert validate_chat_id(chat_id) == chat_id


@pytest.mark.parametrize(
    "chat_id",
    ["", "abc", "12 34", "@shor", "123\n456", "-1001234567890\r\n", "x" * 65],
)
def test_invalid_chat_ids(chat_id):
    with pytest.raises(ValueError):
        validate_chat_id(chat_id)


def test_smtp_host_requires_from():
    with pytest.raises(ValidationError, match="SMTP_FROM"):
        Settings(smtp_host="smtp.test")
    assert Settings(smtp_host="smtp.test", smtp_from="a@b.test").smtp_from == "a@b.test"


# --- request schema -----------------------------------------------------------


def test_handoff_request_schema():
    body = HandoffRequestIn(email="visitor@example.com", message="  Please call me  ")
    assert body.message == "Please call me"
    assert body.website == "" and body.opened_at is None
    with pytest.raises(ValidationError):
        HandoffRequestIn(email="visitor@example.com", message="   ")
    with pytest.raises(ValidationError):
        HandoffRequestIn(email="visitor@example.com", message="hi\x00")
    with pytest.raises(ValidationError):
        HandoffRequestIn(email="not-an-email", message="hi")
    with pytest.raises(ValidationError):
        HandoffRequestIn(email="visitor@example.com", message="hi", language="de")


def test_settings_update_handoff_fields():
    assert SettingsUpdate(handoff_email="").handoff_email == ""
    assert SettingsUpdate().handoff_email is None
    assert SettingsUpdate(handoff_email="a@b.test").handoff_email == "a@b.test"
    assert SettingsUpdate(telegram_chat_id="").telegram_chat_id == ""
    assert SettingsUpdate(telegram_chat_id="-100123").telegram_chat_id == "-100123"
    with pytest.raises(ValidationError):
        SettingsUpdate(handoff_email="a@b.test\r\nBcc: c@d.test")
    with pytest.raises(ValidationError):
        SettingsUpdate(telegram_chat_id="not a chat")


# --- channel planning ---------------------------------------------------------


def test_plan_channels():
    settings = handoff_settings()
    assert plan_channels(make_company(), settings) == (True, True)
    assert plan_channels(make_company(telegram_chat_id=None), settings) == (True, False)
    assert plan_channels(make_company(handoff_email=None), settings) == (False, True)
    assert plan_channels(make_company(handoff_email=None, telegram_chat_id=None), settings) == (
        False,
        False,
    )
    no_smtp = handoff_settings(smtp_host="", smtp_from="")
    assert plan_channels(make_company(), no_smtp) == (False, True)
    no_tg = handoff_settings(telegram_bot_token="")
    assert plan_channels(make_company(), no_tg) == (True, False)


async def test_not_configured_errors_are_actionable():
    company = make_company(handoff_email=None, telegram_chat_id=None)
    with pytest.raises(HandoffError) as exc:
        await request_handoff(
            FakeSession(), company, "v@example.com", "hi", None, handoff_settings()
        )
    assert exc.value.status_code == 409
    assert "Settings" in str(exc.value)

    company = make_company(telegram_chat_id=None)
    with pytest.raises(HandoffError) as exc:
        await request_handoff(
            FakeSession(), company, "v@example.com", "hi", None,
            handoff_settings(smtp_host="", smtp_from=""),
        )
    assert exc.value.status_code == 409
    assert "SMTP_HOST" in str(exc.value)

    company = make_company(handoff_email=None)
    with pytest.raises(HandoffError) as exc:
        await request_handoff(
            FakeSession(), company, "v@example.com", "hi", None,
            handoff_settings(telegram_bot_token=""),
        )
    assert "TELEGRAM_BOT_TOKEN" in str(exc.value)


# --- email building + SMTP delivery -------------------------------------------


def test_build_email_headers_and_body():
    company = make_company(name="Acme\r\nBcc: evil@attacker.test")
    msg = build_email(company, "visitor@example.com", "Please call me", "en", handoff_settings())
    assert msg["From"] == "sanad@sanad.test"
    assert msg["To"] == "support@acme.test"
    assert msg["Reply-To"] == "visitor@example.com"
    assert "\n" not in msg["Subject"] and "\r" not in msg["Subject"]
    assert "Acme" in msg["Subject"]
    body = msg.get_content()
    assert "Please call me" in body
    assert "visitor@example.com" in body
    assert "Language: en" in body


def test_build_email_arabic_body_roundtrip():
    msg = build_email(
        make_company(), "visitor@example.com", "أريد التحدث إلى موظف", "ar", handoff_settings()
    )
    assert "أريد التحدث إلى موظف" in msg.get_content()
    assert msg.get_content_charset() == "utf-8"


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    fail_with: Exception | None = None

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.started = False
        self.logged_in: tuple[str, str] | None = None
        self.sent: list = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        self.started = True

    def login(self, user, password):
        self.logged_in = (user, password)

    def send_message(self, msg):
        if FakeSMTP.fail_with is not None:
            raise FakeSMTP.fail_with
        self.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    FakeSMTP.fail_with = None
    monkeypatch.setattr("app.services.handoff.smtplib.SMTP", FakeSMTP)
    return FakeSMTP


async def test_send_email_starttls_and_no_login(fake_smtp):
    settings = handoff_settings()
    msg = build_email(make_company(), "v@example.com", "hi", "en", settings)
    await send_email(msg, settings)
    smtp = fake_smtp.instances[0]
    assert (smtp.host, smtp.port, smtp.timeout) == ("smtp.test", 587, 15.0)
    assert smtp.started is True
    assert smtp.logged_in is None
    assert smtp.sent == [msg]


async def test_send_email_login_and_no_starttls(fake_smtp):
    settings = handoff_settings(
        smtp_user="mailer", smtp_password="secret", smtp_starttls=False, smtp_port=25
    )
    await send_email(build_email(make_company(), "v@example.com", "hi", "en", settings), settings)
    smtp = fake_smtp.instances[0]
    assert smtp.started is False
    assert smtp.logged_in == ("mailer", "secret")
    assert smtp.port == 25


async def test_send_email_failure_is_actionable_and_hides_password(fake_smtp):
    fake_smtp.fail_with = smtplib.SMTPAuthenticationError(535, b"auth failed")
    settings = handoff_settings(smtp_user="mailer", smtp_password="super-secret-value")
    msg = build_email(make_company(), "v@example.com", "hi", "en", settings)
    with pytest.raises(HandoffError) as exc:
        await send_email(msg, settings)
    assert exc.value.status_code == 502
    assert "SMTP_PASSWORD" in str(exc.value)
    assert "super-secret-value" not in str(exc.value)


async def test_send_email_network_failure(fake_smtp):
    fake_smtp.fail_with = OSError("connection refused")
    with pytest.raises(HandoffError, match="Could not send"):
        await send_email(
            build_email(make_company(), "v@example.com", "hi", "en", handoff_settings()),
            handoff_settings(),
        )


# --- Telegram delivery ---------------------------------------------------------


def test_telegram_text_and_truncation():
    text = telegram_text(make_company(), "v@example.com", "hello", "fr")
    assert "Acme" in text and "v@example.com" in text and "hello" in text
    long = telegram_text(make_company(), "v@example.com", "x" * 5000, "en")
    assert len(long) == 4096


@pytest.fixture
def telegram_transport(monkeypatch):
    recorded: list[httpx.Request] = []
    state = {"response": httpx.Response(200, json={"ok": True, "result": {}})}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return state["response"]

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        return real_client(*args, transport=transport, **kwargs)

    monkeypatch.setattr("app.services.handoff.httpx.AsyncClient", factory)
    return recorded, state


async def test_send_telegram_payload(telegram_transport):
    recorded, _ = telegram_transport
    settings = handoff_settings()
    await send_telegram(make_company(), "v@example.com", "hello", "en", settings)
    request = recorded[0]
    assert request.url.path == "/bot123:TEST-TOKEN/sendMessage"
    assert request.url.host == "api.telegram.org"
    payload = json.loads(request.content)
    assert payload["chat_id"] == "123456"
    assert "hello" in payload["text"]
    assert payload["disable_web_page_preview"] is True


async def test_send_telegram_http_error_hides_token(telegram_transport):
    recorded, state = telegram_transport
    state["response"] = httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
    with pytest.raises(HandoffError) as exc:
        await send_telegram(make_company(), "v@example.com", "hi", "en", handoff_settings())
    assert "TELEGRAM_BOT_TOKEN" in str(exc.value)
    assert "123:TEST-TOKEN" not in str(exc.value)
    assert len(recorded) == 1


async def test_send_telegram_not_ok(telegram_transport):
    _, state = telegram_transport
    state["response"] = httpx.Response(
        200, json={"ok": False, "description": "chat not found"}
    )
    with pytest.raises(HandoffError, match="chat not found"):
        await send_telegram(make_company(), "v@example.com", "hi", "en", handoff_settings())


async def test_send_telegram_non_json(telegram_transport):
    _, state = telegram_transport
    state["response"] = httpx.Response(200, text="<html>proxy error</html>")
    with pytest.raises(HandoffError, match="unexpected response"):
        await send_telegram(make_company(), "v@example.com", "hi", "en", handoff_settings())


async def test_send_telegram_unreachable(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("no route", request=request)

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.services.handoff.httpx.AsyncClient",
        lambda *a, **kw: real_client(*a, transport=transport, **kw),
    )
    with pytest.raises(HandoffError, match="Could not reach Telegram"):
        await send_telegram(make_company(), "v@example.com", "hi", "en", handoff_settings())


async def test_send_telegram_custom_base(telegram_transport):
    recorded, _ = telegram_transport
    settings = handoff_settings(telegram_api_base="http://127.0.0.1:9000/")
    await send_telegram(make_company(), "v@example.com", "hi", "en", settings)
    assert recorded[0].url.host == "127.0.0.1"
    assert recorded[0].url.port == 9000


# --- orchestration + privacy ----------------------------------------------------


class FakeSession:
    def __init__(self):
        self.added: list = []
        self.commits = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


@pytest.fixture
def channels(monkeypatch):
    state = {"email": "ok", "telegram": "ok"}

    async def fake_email(msg, settings):
        if state["email"] != "ok":
            raise HandoffError("email broke")

    async def fake_telegram(company, email, message, language, settings):
        if state["telegram"] != "ok":
            raise HandoffError("telegram broke")

    monkeypatch.setattr("app.services.handoff.send_email", fake_email)
    monkeypatch.setattr("app.services.handoff.send_telegram", fake_telegram)
    return state


async def test_request_handoff_both_channels_stored(channels):
    session = FakeSession()
    outcome = await request_handoff(
        session, make_company(), "v@example.com", "Please call me", None, handoff_settings()
    )
    assert outcome.email is ChannelStatus.SENT
    assert outcome.telegram is ChannelStatus.SENT
    assert outcome.stored is True
    row = session.added[0]
    assert isinstance(row, HandoffRequest)
    assert row.company_id == COMPANY_ID
    assert row.email == "v@example.com"
    assert row.message == "Please call me"
    assert row.language == "en"
    assert row.error is None
    assert session.commits == 1


async def test_request_handoff_detects_arabic(channels):
    session = FakeSession()
    await request_handoff(
        session, make_company(), "v@example.com", "أريد التحدث إلى موظف من فضلكم", None,
        handoff_settings(),
    )
    assert session.added[0].language == "ar"


async def test_request_handoff_privacy_toggle_skips_storage(channels):
    session = FakeSession()
    outcome = await request_handoff(
        session, make_company(store_conversations=False), "v@example.com", "hi", "fr",
        handoff_settings(),
    )
    assert outcome.stored is False
    assert outcome.email is ChannelStatus.SENT
    assert session.added == []
    assert session.commits == 0


async def test_request_handoff_partial_failure_still_delivers(channels):
    channels["email"] = "fail"
    session = FakeSession()
    outcome = await request_handoff(
        session, make_company(), "v@example.com", "hi", None, handoff_settings()
    )
    assert outcome.email is ChannelStatus.FAILED
    assert outcome.telegram is ChannelStatus.SENT
    assert "email broke" in session.added[0].error


async def test_request_handoff_total_failure_raises_after_storing(channels):
    channels["email"] = channels["telegram"] = "fail"
    session = FakeSession()
    with pytest.raises(HandoffError) as exc:
        await request_handoff(
            session, make_company(), "v@example.com", "hi", None, handoff_settings()
        )
    assert exc.value.status_code == 502
    assert "email broke" in str(exc.value) and "telegram broke" in str(exc.value)
    row = session.added[0]
    assert row.email_status is ChannelStatus.FAILED
    assert row.telegram_status is ChannelStatus.FAILED


async def test_request_handoff_skipped_channels(channels):
    session = FakeSession()
    outcome = await request_handoff(
        session, make_company(telegram_chat_id=None), "v@example.com", "hi", None,
        handoff_settings(),
    )
    assert outcome.telegram is ChannelStatus.SKIPPED
    assert session.added[0].telegram_status is ChannelStatus.SKIPPED


# --- handoff rate limits ---------------------------------------------------------


async def test_handoff_per_ip_limit():
    kv = MemoryKVStore()
    settings = handoff_settings(handoff_rate_limit_per_ip=2)
    request = make_request()
    await enforce_handoff_limits(kv, request, COMPANY_ID, settings)
    await enforce_handoff_limits(kv, request, COMPANY_ID, settings)
    with pytest.raises(HTTPException) as exc:
        await enforce_handoff_limits(kv, request, COMPANY_ID, settings)
    assert exc.value.status_code == 429
    assert "handoff requests/minute per IP" in exc.value.detail
    assert 1 <= int(exc.value.headers["Retry-After"]) <= 60


async def test_handoff_daily_cap_per_company():
    kv = MemoryKVStore()
    settings = handoff_settings(handoff_daily_cap_per_company=1)
    await enforce_handoff_limits(kv, make_request(), COMPANY_ID, settings)
    with pytest.raises(HTTPException) as exc:
        await enforce_handoff_limits(kv, make_request("5.6.7.8"), COMPANY_ID, settings)
    assert exc.value.status_code == 429
    assert "handoff requests/day" in exc.value.detail
    other = uuid.uuid4()
    await enforce_handoff_limits(kv, make_request(), other, settings)


async def test_handoff_limits_disabled_and_fail_open():
    kv = MemoryKVStore()
    settings = handoff_settings()
    for _ in range(10):
        await enforce_handoff_limits(kv, make_request(), COMPANY_ID, settings)
    limited = handoff_settings(handoff_rate_limit_per_ip=1, handoff_daily_cap_per_company=1)
    for _ in range(3):
        await enforce_handoff_limits(BrokenKV(), make_request(), COMPANY_ID, limited)


async def test_handoff_buckets_separate_from_chat():
    kv = MemoryKVStore()
    settings = handoff_settings(handoff_rate_limit_per_ip=1)
    await enforce_handoff_limits(kv, make_request(), COMPANY_ID, settings)
    with pytest.raises(HTTPException):
        await enforce_handoff_limits(kv, make_request(), COMPANY_ID, settings)
    # The chat bucket for the same IP is untouched.
    from app.services.rate_limit import enforce_chat_limits

    chat_settings = Settings(rate_limit_per_ip=1, rate_limit_per_site=0, daily_cap_per_company=0)
    await enforce_chat_limits(kv, make_request(), COMPANY_ID, chat_settings)


async def test_handoff_window_rolls_over(monkeypatch):
    kv = MemoryKVStore()
    settings = handoff_settings(handoff_rate_limit_per_ip=1)
    now = [1000.0]
    monkeypatch.setattr("app.services.rate_limit.time.time", lambda: now[0])
    await enforce_handoff_limits(kv, make_request(), COMPANY_ID, settings)
    with pytest.raises(HTTPException):
        await enforce_handoff_limits(kv, make_request(), COMPANY_ID, settings)
    now[0] = 1061.0
    await enforce_handoff_limits(kv, make_request(), COMPANY_ID, settings)