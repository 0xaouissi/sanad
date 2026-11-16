"""In-memory KV store: TTL, atomic counters, prefix deletion."""

import time

import pytest

from app.providers.kv.memory import MemoryKVStore


@pytest.fixture
def store() -> MemoryKVStore:
    return MemoryKVStore()


async def test_set_get_roundtrip(store):
    assert await store.get("missing") is None
    await store.set("k", "v")
    assert await store.get("k") == "v"


async def test_ttl_expiry(store, monkeypatch):
    now = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    await store.set("k", "v", ttl_seconds=10)
    assert await store.get("k") == "v"
    now = 1010.0
    assert await store.get("k") is None


async def test_no_ttl_never_expires(store, monkeypatch):
    now = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    await store.set("k", "v")
    now = 10**9
    assert await store.get("k") == "v"


async def test_incr_counts_and_sets_ttl_once(store, monkeypatch):
    now = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: now)
    assert await store.incr("c", ttl_seconds=60) == 1
    assert await store.incr("c", ttl_seconds=60) == 2
    assert await store.incr("c", ttl_seconds=60) == 3
    now = 1059.0
    assert await store.incr("c", ttl_seconds=60) == 4
    now = 1060.0
    # Window expired: counter restarts with a fresh TTL.
    assert await store.incr("c", ttl_seconds=60) == 1


async def test_delete_prefix(store):
    await store.set("chat:a:1", "x")
    await store.set("chat:a:2", "y")
    await store.set("chat:b:1", "z")
    await store.set("other", "w")
    assert await store.delete_prefix("chat:a:") == 2
    assert await store.get("chat:a:1") is None
    assert await store.get("chat:b:1") == "z"
    assert await store.get("other") == "w"