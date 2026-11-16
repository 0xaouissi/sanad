"""Answer cache: company/language-scoped keys, epoch invalidation, fail-open."""

import uuid

import pytest
from redis.exceptions import RedisError

from app.core import metrics
from app.providers.kv.base import KVStore
from app.providers.kv.memory import MemoryKVStore
from app.services.answer_cache import (
    answer_cache_key,
    bump_doc_epoch,
    get_cached_answer,
    store_answer,
)

COMPANY_A = uuid.uuid4()
COMPANY_B = uuid.uuid4()
PAYLOAD = {"answer": "30 days [1]", "citations": []}


@pytest.fixture(autouse=True)
def _clean_metrics():
    metrics.reset()
    yield
    metrics.reset()


def test_key_includes_company_language_question_and_epoch():
    base = answer_cache_key(COMPANY_A, "en", "refund?", 0)
    assert str(COMPANY_A) in base
    assert ":en:" in base
    assert base != answer_cache_key(COMPANY_B, "en", "refund?", 0)
    assert base != answer_cache_key(COMPANY_A, "fr", "refund?", 0)
    assert base != answer_cache_key(COMPANY_A, "en", "shipping?", 0)
    assert base != answer_cache_key(COMPANY_A, "en", "refund?", 1)


async def test_store_and_get_roundtrip():
    kv = MemoryKVStore()
    assert await get_cached_answer(kv, COMPANY_A, "en", "refund?") is None
    await store_answer(kv, COMPANY_A, "en", "refund?", PAYLOAD)
    assert await get_cached_answer(kv, COMPANY_A, "en", "refund?") == PAYLOAD
    # Other companies and languages never see it.
    assert await get_cached_answer(kv, COMPANY_B, "en", "refund?") is None
    assert await get_cached_answer(kv, COMPANY_A, "fr", "refund?") is None
    assert metrics.snapshot()["cache_hits_total"] == 1
    assert metrics.snapshot()["cache_misses_total"] == 3


async def test_epoch_bump_invalidates_company_answers():
    kv = MemoryKVStore()
    await store_answer(kv, COMPANY_A, "en", "refund?", PAYLOAD)
    await store_answer(kv, COMPANY_B, "en", "refund?", PAYLOAD)
    await bump_doc_epoch(kv, COMPANY_A)
    assert await get_cached_answer(kv, COMPANY_A, "en", "refund?") is None
    assert await get_cached_answer(kv, COMPANY_B, "en", "refund?") == PAYLOAD


async def test_corrupt_payload_is_a_miss():
    kv = MemoryKVStore()
    key = answer_cache_key(COMPANY_A, "en", "refund?", 0)
    await kv.set(key, "{not json")
    assert await get_cached_answer(kv, COMPANY_A, "en", "refund?") is None


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


async def test_backend_failure_degrades_to_miss():
    kv = BrokenKV()
    assert await get_cached_answer(kv, COMPANY_A, "en", "refund?") is None
    await store_answer(kv, COMPANY_A, "en", "refund?", PAYLOAD)  # must not raise
    await bump_doc_epoch(kv, COMPANY_A)  # must not raise