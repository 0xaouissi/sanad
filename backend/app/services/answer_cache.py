"""Grounded-answer cache.

Keys embed the company id, the answer language, the exact question and a
per-company document epoch: answers can never leak between companies or
languages, and any document change invalidates the company's cached answers.
Backend failures degrade to a cache miss — chat keeps working.
"""

import hashlib
import json
import uuid

import structlog
from redis.exceptions import RedisError

from app.core import metrics
from app.core.config import get_settings
from app.providers.kv.base import KVStore

log = structlog.get_logger()


def _epoch_key(company_id: uuid.UUID) -> str:
    return f"docepoch:{company_id}"


def answer_cache_key(
    company_id: uuid.UUID, language: str, question: str, epoch: int
) -> str:
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()
    # v2: payloads carry refusal_kind; v1 entries predate the refusal split.
    return f"chat:v2:{company_id}:{language}:{digest}:{epoch}"


async def bump_doc_epoch(kv: KVStore, company_id: uuid.UUID) -> None:
    try:
        await kv.incr(_epoch_key(company_id))
    except (RedisError, OSError) as exc:
        log.warning("cache_epoch_bump_failed", detail=str(exc))


async def get_cached_answer(
    kv: KVStore, company_id: uuid.UUID, language: str, question: str
) -> dict | None:
    try:
        raw_epoch = await kv.get(_epoch_key(company_id))
        key = answer_cache_key(company_id, language, question, int(raw_epoch or 0))
        raw = await kv.get(key)
    except (RedisError, OSError) as exc:
        log.warning("cache_read_failed", detail=str(exc))
        return None
    if raw is None:
        metrics.inc("cache_misses_total")
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    metrics.inc("cache_hits_total")
    return payload


async def store_answer(
    kv: KVStore, company_id: uuid.UUID, language: str, question: str, payload: dict
) -> None:
    try:
        raw_epoch = await kv.get(_epoch_key(company_id))
        key = answer_cache_key(company_id, language, question, int(raw_epoch or 0))
        await kv.set(key, json.dumps(payload, ensure_ascii=False), get_settings().cache_ttl_seconds)
    except (RedisError, OSError) as exc:
        log.warning("cache_write_failed", detail=str(exc))