"""In-memory KV store: the default backend when REDIS_URL is unset.

Single-process only — with multiple workers each keeps its own counters and
cache. Set REDIS_URL for shared state across workers/replicas.
"""

import asyncio
import time

from app.providers.kv.base import KVStore


class MemoryKVStore(KVStore):
    name = "memory"

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self._lock = asyncio.Lock()

    def _expired(self, expires_at: float | None) -> bool:
        return expires_at is not None and time.monotonic() >= expires_at

    async def get(self, key: str) -> str | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if self._expired(expires_at):
                del self._data[key]
                return None
            return value

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds is not None else None
        async with self._lock:
            self._data[key] = (value, expires_at)

    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None or self._expired(entry[1]):
                expires_at = time.monotonic() + ttl_seconds if ttl_seconds is not None else None
                self._data[key] = ("1", expires_at)
                return 1
            value = int(entry[0]) + 1
            self._data[key] = (str(value), entry[1])
            return value

    async def delete_prefix(self, prefix: str) -> int:
        async with self._lock:
            keys = [k for k in self._data if k.startswith(prefix)]
            for key in keys:
                del self._data[key]
            return len(keys)

    async def ping(self) -> None:
        return None

    async def aclose(self) -> None:
        return None