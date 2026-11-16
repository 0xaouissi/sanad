"""Fixed-window rate limits: per IP, per site, daily cap, fail-open."""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from app.core.config import Settings
from app.providers.kv.base import KVStore
from app.providers.kv.memory import MemoryKVStore
from app.services.rate_limit import _seconds_to_utc_midnight, client_ip, enforce_chat_limits

COMPANY = uuid.uuid4()


def make_request(ip: str = "1.2.3.4", headers: dict[str, str] | None = None) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/chat",
            "query_string": b"",
            "headers": [
                (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
            ],
            "client": (ip, 12345),
            "scheme": "http",
            "server": ("test", 80),
        }
    )


def limits(**overrides) -> Settings:
    base = {"rate_limit_per_ip": 0, "rate_limit_per_site": 0, "daily_cap_per_company": 0}
    return Settings(**{**base, **overrides})


async def test_per_ip_limit_blocks_third_request():
    kv = MemoryKVStore()
    settings = limits(rate_limit_per_ip=2)
    request = make_request()
    await enforce_chat_limits(kv, request, COMPANY, settings)
    await enforce_chat_limits(kv, request, COMPANY, settings)
    with pytest.raises(HTTPException) as exc:
        await enforce_chat_limits(kv, request, COMPANY, settings)
    assert exc.value.status_code == 429
    assert "per IP" in exc.value.detail
    assert 1 <= int(exc.value.headers["Retry-After"]) <= 60


async def test_per_site_limit():
    kv = MemoryKVStore()
    settings = limits(rate_limit_per_site=1)
    await enforce_chat_limits(kv, make_request(), COMPANY, settings)
    with pytest.raises(HTTPException) as exc:
        await enforce_chat_limits(kv, make_request("5.6.7.8"), COMPANY, settings)
    assert exc.value.status_code == 429
    assert "per site" in exc.value.detail


async def test_daily_cap():
    kv = MemoryKVStore()
    settings = limits(daily_cap_per_company=1)
    await enforce_chat_limits(kv, make_request(), COMPANY, settings)
    with pytest.raises(HTTPException) as exc:
        await enforce_chat_limits(kv, make_request("5.6.7.8"), COMPANY, settings)
    assert exc.value.status_code == 429
    assert "chats/day" in exc.value.detail
    assert int(exc.value.headers["Retry-After"]) >= 1


async def test_zero_disables_all_limits():
    kv = MemoryKVStore()
    settings = limits()
    for _ in range(5):
        await enforce_chat_limits(kv, make_request(), COMPANY, settings)


async def test_separate_ips_have_separate_buckets():
    kv = MemoryKVStore()
    settings = limits(rate_limit_per_ip=1)
    await enforce_chat_limits(kv, make_request("1.1.1.1"), COMPANY, settings)
    with pytest.raises(HTTPException):
        await enforce_chat_limits(kv, make_request("1.1.1.1"), COMPANY, settings)
    await enforce_chat_limits(kv, make_request("2.2.2.2"), COMPANY, settings)


async def test_separate_companies_have_separate_buckets():
    kv = MemoryKVStore()
    settings = limits(rate_limit_per_site=1)
    other = uuid.uuid4()
    await enforce_chat_limits(kv, make_request(), COMPANY, settings)
    with pytest.raises(HTTPException):
        await enforce_chat_limits(kv, make_request(), COMPANY, settings)
    await enforce_chat_limits(kv, make_request(), other, settings)


async def test_minute_window_rolls_over(monkeypatch):
    kv = MemoryKVStore()
    settings = limits(rate_limit_per_ip=1)
    now = [1000.0]
    monkeypatch.setattr("app.services.rate_limit.time.time", lambda: now[0])
    await enforce_chat_limits(kv, make_request(), COMPANY, settings)
    with pytest.raises(HTTPException):
        await enforce_chat_limits(kv, make_request(), COMPANY, settings)
    now[0] = 1061.0
    await enforce_chat_limits(kv, make_request(), COMPANY, settings)


async def test_forwarded_for_used_only_when_trusted():
    kv = MemoryKVStore()
    settings = limits(rate_limit_per_ip=1, trust_forwarded_for=True)
    headers = {"X-Forwarded-For": "9.9.9.9, 10.0.0.1"}
    await enforce_chat_limits(kv, make_request(headers=headers), COMPANY, settings)
    with pytest.raises(HTTPException):
        await enforce_chat_limits(kv, make_request(headers=headers), COMPANY, settings)
    await enforce_chat_limits(
        kv, make_request(headers={"X-Forwarded-For": "8.8.8.8"}), COMPANY, settings
    )
    assert client_ip(make_request(headers=headers), settings) == "9.9.9.9"

    untrusted = limits(rate_limit_per_ip=1)
    kv2 = MemoryKVStore()
    await enforce_chat_limits(kv2, make_request(headers=headers), COMPANY, untrusted)
    with pytest.raises(HTTPException):
        await enforce_chat_limits(
            kv2, make_request(headers={"X-Forwarded-For": "8.8.8.8"}), COMPANY, untrusted
        )


def test_seconds_to_utc_midnight():
    assert _seconds_to_utc_midnight(datetime(2026, 11, 16, 23, 59, 30, tzinfo=UTC)) == 30
    assert _seconds_to_utc_midnight(datetime(2026, 11, 16, 0, 0, 0, tzinfo=UTC)) == 86400


class BrokenKV(KVStore):
    async def get(self, key):
        raise RedisError("connection lost")

    async def set(self, key, value, ttl_seconds=None):
        raise RedisError("connection lost")

    async def incr(self, key, ttl_seconds=None):
        raise RedisError("connection lost")

    async def delete_prefix(self, prefix):
        raise RedisError("connection lost")

    async def ping(self):
        raise RedisError("connection lost")

    async def aclose(self):
        raise RedisError("connection lost")


async def test_backend_failure_fails_open():
    settings = limits(rate_limit_per_ip=1, rate_limit_per_site=1, daily_cap_per_company=1)
    for _ in range(3):
        await enforce_chat_limits(BrokenKV(), make_request(), COMPANY, settings)