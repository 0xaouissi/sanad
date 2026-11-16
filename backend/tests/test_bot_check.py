"""Bot deterrent: honeypot + minimum open time, site-key path only."""

import time

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.schemas.chat import ChatRequest
from app.services.bot_check import enforce_bot_check


def settings(**overrides) -> Settings:
    return Settings(**overrides)


def test_honeypot_filled_is_rejected():
    request = ChatRequest(message="hi", website="http://spam.example", opened_at=0)
    with pytest.raises(HTTPException) as exc:
        enforce_bot_check(request, True, settings())
    assert exc.value.status_code == 400
    assert "website" in exc.value.detail


def test_missing_opened_at_is_rejected():
    with pytest.raises(HTTPException) as exc:
        enforce_bot_check(ChatRequest(message="hi"), True, settings())
    assert exc.value.status_code == 400
    assert "opened_at" in exc.value.detail


def test_sending_too_fast_is_rejected_with_retry_after():
    request = ChatRequest(message="hi", opened_at=time.time() * 1000)
    with pytest.raises(HTTPException) as exc:
        enforce_bot_check(request, True, settings(bot_check_min_seconds=2.0))
    assert exc.value.status_code == 429
    assert 1 <= int(exc.value.headers["Retry-After"]) <= 2


def test_future_opened_at_is_rejected():
    request = ChatRequest(message="hi", opened_at=(time.time() + 60) * 1000)
    with pytest.raises(HTTPException):
        enforce_bot_check(request, True, settings())


def test_patient_visitor_passes():
    request = ChatRequest(message="hi", opened_at=(time.time() - 5) * 1000)
    enforce_bot_check(request, True, settings())


def test_secret_key_path_is_exempt():
    request = ChatRequest(message="hi", website="spam", opened_at=None)
    enforce_bot_check(request, False, settings())


def test_disabled_check_is_exempt():
    request = ChatRequest(message="hi", website="spam", opened_at=None)
    enforce_bot_check(request, True, settings(bot_check_enabled=False))


def test_zero_min_seconds_still_requires_opened_at():
    enforce_bot_check(
        ChatRequest(message="hi", opened_at=time.time() * 1000),
        True,
        settings(bot_check_min_seconds=0),
    )
    with pytest.raises(HTTPException):
        enforce_bot_check(ChatRequest(message="hi"), True, settings(bot_check_min_seconds=0))