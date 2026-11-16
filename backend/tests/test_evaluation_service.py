"""Unit tests: evaluation run-slot claiming and state handling (KV only)."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from app.providers.kv.memory import MemoryKVStore
from app.services.evaluation import get_eval_state, start_eval


async def test_start_eval_claims_once() -> None:
    kv = MemoryKVStore()
    company_id = uuid.uuid4()
    assert await start_eval(kv, company_id) is True
    state = await get_eval_state(kv, company_id)
    assert state["status"] == "running"
    assert state["total"] == 33
    assert await start_eval(kv, company_id) is False


async def test_stale_running_run_can_be_reclaimed() -> None:
    kv = MemoryKVStore()
    company_id = uuid.uuid4()
    stale = {
        "status": "running",
        "started_at": (datetime.now(UTC) - timedelta(minutes=31)).isoformat(),
    }
    await kv.set(f"eval:{company_id}", json.dumps(stale))
    assert await start_eval(kv, company_id) is True


async def test_finished_or_corrupt_state_can_be_reclaimed() -> None:
    kv = MemoryKVStore()
    company_id = uuid.uuid4()
    await kv.set(f"eval:{company_id}", json.dumps({"status": "done"}))
    assert await start_eval(kv, company_id) is True
    await kv.set(f"eval:{company_id}", "not-json")
    assert await get_eval_state(kv, company_id) is None
    assert await start_eval(kv, company_id) is True


async def test_state_is_scoped_per_company() -> None:
    kv = MemoryKVStore()
    first, second = uuid.uuid4(), uuid.uuid4()
    await start_eval(kv, first)
    assert await get_eval_state(kv, second) is None
    assert await start_eval(kv, second) is True