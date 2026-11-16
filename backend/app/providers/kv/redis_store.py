"""Redis KV store (redis.asyncio). Used when REDIS_URL is set."""

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.providers.kv.base import KVStore

# Atomic INCR + first-creation EXPIRE. Plain INCR then EXPIRE would leave a
# counter without TTL if the process died in between; EXPIRE NX needs Redis 7.
_INCR_LUA = """
local value = redis.call('INCR', KEYS[1])
if value == 1 and ARGV[1] ~= '' then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return value
"""


class RedisKVStore(KVStore):
    name = "redis"

    def __init__(self, url: str) -> None:
        # protocol=2: RESP3 (HELLO) needs Redis 7+; keep compatibility with
        # older servers such as the native Windows Redis 5 build.
        self._redis = Redis.from_url(url, decode_responses=True, protocol=2)
        self._incr = self._redis.register_script(_INCR_LUA)

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        if ttl_seconds is None:
            await self._redis.set(key, value)
        else:
            await self._redis.set(key, value, ex=ttl_seconds)

    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        return int(await self._incr(keys=[key], args=[str(ttl_seconds or "")]))

    async def delete_prefix(self, prefix: str) -> int:
        deleted = 0
        async for key in self._redis.scan_iter(match=f"{prefix}*", count=200):
            await self._redis.unlink(key)
            deleted += 1
        return deleted

    async def ping(self) -> None:
        await self._redis.ping()

    async def aclose(self) -> None:
        await self._redis.aclose()


__all__ = ["RedisKVStore", "RedisError"]