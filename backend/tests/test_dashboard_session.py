import time
import uuid

from app.core.config import Settings
from app.providers.kv.memory import MemoryKVStore
from app.services.dashboard_session import create_session, delete_session, get_session


async def test_session_roundtrip() -> None:
    kv = MemoryKVStore()
    user_id, company_id = uuid.uuid4(), uuid.uuid4()
    token, data = await create_session(kv, user_id, company_id, Settings())
    assert len(token) >= 32
    assert data.csrf and data.csrf != token
    loaded = await get_session(kv, token)
    assert loaded is not None
    assert loaded.user_id == user_id
    assert loaded.company_id == company_id
    assert loaded.csrf == data.csrf


async def test_unknown_token_is_none() -> None:
    assert await get_session(MemoryKVStore(), "no-such-token") is None


async def test_delete_session() -> None:
    kv = MemoryKVStore()
    token, _ = await create_session(kv, uuid.uuid4(), uuid.uuid4(), Settings())
    await delete_session(kv, token)
    assert await get_session(kv, token) is None


async def test_corrupt_payload_is_none() -> None:
    kv = MemoryKVStore()
    await kv.set("sess:broken", "{not json")
    assert await get_session(kv, "broken") is None
    await kv.set("sess:missing-fields", '{"user_id": "x"}')
    assert await get_session(kv, "missing-fields") is None


async def test_session_has_ttl() -> None:
    kv = MemoryKVStore()
    settings = Settings(dashboard_session_hours=2)
    token, _ = await create_session(kv, uuid.uuid4(), uuid.uuid4(), settings)
    _, expires_at = kv._data[f"sess:{token}"]
    assert expires_at is not None
    assert expires_at > time.monotonic() + 7000