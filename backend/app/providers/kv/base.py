"""Key-value store interface shared by the answer cache and rate limits."""

from abc import ABC, abstractmethod


class KVStore(ABC):
    name: str = "kv"

    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        """Store a value; None ttl = no expiry."""

    @abstractmethod
    async def incr(self, key: str, ttl_seconds: int | None = None) -> int:
        """Atomically increment a counter, setting ttl when it is first created."""

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> int:
        """Delete all keys starting with prefix; returns the number deleted."""

    @abstractmethod
    async def ping(self) -> None:
        """Raise when the backend is unreachable."""

    @abstractmethod
    async def aclose(self) -> None: ...