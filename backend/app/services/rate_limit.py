"""Fixed-window abuse limits on visitor chat: per IP, per site, per UTC day.

Counters live in the KV store (Redis when configured, in-memory otherwise).
A limit of 0 disables that check. Backend failures fail open so a Redis
outage never takes chat down. Returns 429 with Retry-After when exceeded.
"""

import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from fastapi import HTTPException, Request
from redis.exceptions import RedisError

from app.core import metrics
from app.core.config import Settings
from app.providers.kv.base import KVStore

log = structlog.get_logger()


def client_ip(request: Request, settings: Settings) -> str:
    if settings.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def _seconds_to_utc_midnight(now: datetime) -> int:
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((tomorrow - now).total_seconds()))


async def enforce_login_limit(kv: KVStore, request: Request, settings: Settings) -> None:
    limit = settings.login_rate_limit_per_minute
    if limit <= 0:
        return
    now = time.time()
    minute = int(now // 60)
    retry_after = max(1, 60 - int(now % 60))
    key = f"rl:login:{client_ip(request, settings)}:{minute}"
    try:
        count = await kv.incr(key, ttl_seconds=retry_after)
    except (RedisError, OSError) as exc:
        log.warning("rate_limit_backend_unavailable", detail=str(exc))
        return
    if count > limit:
        metrics.inc("rate_limited_total")
        log.info("rate_limited", key=key, count=count, limit=limit)
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts: limit is {limit}/minute per IP. "
            f"Retry in {retry_after} seconds.",
            headers={"Retry-After": str(retry_after)},
        )


async def _enforce_checks(kv: KVStore, checks: list[tuple[str, int, int, str]]) -> None:
    for key, limit, retry_after, label in checks:
        try:
            count = await kv.incr(key, ttl_seconds=retry_after)
        except (RedisError, OSError) as exc:
            log.warning("rate_limit_backend_unavailable", detail=str(exc))
            return
        if count > limit:
            metrics.inc("rate_limited_total")
            log.info("rate_limited", key=key, count=count, limit=limit)
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests: limit is {label}. "
                f"Retry in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)},
            )


async def enforce_chat_limits(
    kv: KVStore, request: Request, company_id: UUID, settings: Settings
) -> None:
    now = time.time()
    minute = int(now // 60)
    minute_retry = max(1, 60 - int(now % 60))
    checks: list[tuple[str, int, int, str]] = []
    if settings.rate_limit_per_ip > 0:
        checks.append(
            (
                f"rl:ip:{client_ip(request, settings)}:{minute}",
                settings.rate_limit_per_ip,
                minute_retry,
                f"{settings.rate_limit_per_ip} requests/minute per IP",
            )
        )
    if settings.rate_limit_per_site > 0:
        checks.append(
            (
                f"rl:site:{company_id}:{minute}",
                settings.rate_limit_per_site,
                minute_retry,
                f"{settings.rate_limit_per_site} requests/minute per site",
            )
        )
    if settings.daily_cap_per_company > 0:
        utc_now = datetime.now(UTC)
        checks.append(
            (
                f"rl:day:{company_id}:{utc_now:%Y-%m-%d}",
                settings.daily_cap_per_company,
                _seconds_to_utc_midnight(utc_now),
                f"{settings.daily_cap_per_company} chats/day for this company",
            )
        )
    await _enforce_checks(kv, checks)


async def enforce_handoff_limits(
    kv: KVStore, request: Request, company_id: UUID, settings: Settings
) -> None:
    now = time.time()
    minute = int(now // 60)
    minute_retry = max(1, 60 - int(now % 60))
    checks: list[tuple[str, int, int, str]] = []
    if settings.handoff_rate_limit_per_ip > 0:
        checks.append(
            (
                f"rl:handoff-ip:{client_ip(request, settings)}:{minute}",
                settings.handoff_rate_limit_per_ip,
                minute_retry,
                f"{settings.handoff_rate_limit_per_ip} handoff requests/minute per IP",
            )
        )
    if settings.handoff_daily_cap_per_company > 0:
        utc_now = datetime.now(UTC)
        checks.append(
            (
                f"rl:handoff-day:{company_id}:{utc_now:%Y-%m-%d}",
                settings.handoff_daily_cap_per_company,
                _seconds_to_utc_midnight(utc_now),
                f"{settings.handoff_daily_cap_per_company} handoff requests/day "
                "for this company",
            )
        )
    await _enforce_checks(kv, checks)