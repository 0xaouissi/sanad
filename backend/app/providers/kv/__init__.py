"""KV store selection: Redis when REDIS_URL is set, in-memory otherwise.

If Redis is configured but unreachable at startup, the app logs a warning
and falls back to the in-memory store instead of refusing to start.
"""

import structlog
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.providers.kv.base import KVStore
from app.providers.kv.memory import MemoryKVStore
from app.providers.kv.redis_store import RedisKVStore

log = structlog.get_logger()

_store: KVStore | None = None


def get_kv_store() -> KVStore:
    global _store
    if _store is None:
        settings = get_settings()
        _store = RedisKVStore(settings.redis_url) if settings.redis_url else MemoryKVStore()
    return _store


def set_kv_store(store: KVStore | None) -> None:
    """Test/override hook; None resets to the configured backend."""
    global _store
    _store = store


async def init_kv() -> KVStore:
    store = get_kv_store()
    if isinstance(store, RedisKVStore):
        try:
            await store.ping()
        except (RedisError, OSError) as exc:
            log.warning(
                "redis_unavailable_memory_fallback",
                redis_url=get_settings().redis_url,
                detail=str(exc),
                hint="Start Redis or unset REDIS_URL to silence this warning.",
            )
            await store.aclose()
            store = MemoryKVStore()
            set_kv_store(store)
    log.info("kv_ready", backend=store.name)
    return store


async def close_kv() -> None:
    global _store
    if _store is not None:
        await _store.aclose()
        _store = None