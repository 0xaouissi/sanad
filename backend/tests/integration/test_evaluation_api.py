"""Evaluation API: background golden run, deterministic scoring, roles, isolation.

The scripted LLM returns the English refusal template for every call, which
makes the injection and English out-of-scope outcomes deterministic regardless
of what the fake retriever returns: both paths end in NO_ANSWER["en"].
"""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core import metrics
from app.db.models import Conversation, Message
from app.db.session import get_session_factory
from app.eval.golden import load_golden, read_samples
from app.providers.kv import get_kv_store
from app.services.rag_chat import NO_ANSWER
from tests.integration.conftest import ADMIN_KEY, FakeEmbedder

OWNER_EMAIL = "eval-owner@acme.com"
OWNER_PASSWORD = "owner-password-1"


@pytest.fixture
async def eval_client(client, fake_llm, monkeypatch):
    fake = FakeEmbedder()
    monkeypatch.setattr("app.services.evaluation.get_embedding_provider", lambda: fake)
    monkeypatch.setattr("app.services.evaluation.get_llm_provider", lambda: fake_llm)
    monkeypatch.setattr("app.services.evaluation.get_rerank_provider", lambda: None)
    return client


async def _owner_session(client, email: str = OWNER_EMAIL) -> dict:
    response = await client.post(
        "/api/v1/companies",
        json={"name": "Eval Co", "owner_email": email, "owner_password": OWNER_PASSWORD},
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    assert response.status_code == 201, response.text
    company = response.json()
    response = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": OWNER_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"company": company, "csrf": response.json()["csrf_token"]}


def _csrf(token: str) -> dict:
    return {"X-CSRF-Token": token}


async def _upload_demo_docs(client, api_key: str) -> None:
    for filename, data in read_samples():
        response = await client.post(
            "/api/v1/documents", files={"file": (filename, data)}, headers={"X-API-Key": api_key}
        )
        assert response.status_code == 202, response.text


async def test_eval_idle_state_reports_golden_counts(eval_client) -> None:
    await _owner_session(eval_client)
    response = await eval_client.get("/api/v1/dashboard/eval")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "idle"
    assert body["documents_ready"] is False
    assert body["golden"]["total"] == 33
    assert body["golden"]["per_language"] == {"en": 11, "fr": 11, "ar": 11}
    assert body["golden"]["per_category"] == {"grounded": 12, "out_of_scope": 15, "injection": 6}


async def test_eval_run_scores_deterministically_and_persists_nothing(
    eval_client, fake_llm
) -> None:
    session = await _owner_session(eval_client)
    await _upload_demo_docs(eval_client, session["company"]["api_key"])
    fake_llm.answers = [NO_ANSWER["en"]]

    response = await eval_client.post("/api/v1/dashboard/eval/run", headers=_csrf(session["csrf"]))
    assert response.status_code == 202, response.text
    # Background tasks complete within the request under ASGITransport.
    body = (await eval_client.get("/api/v1/dashboard/eval")).json()
    assert body["status"] == "done", body.get("error")
    assert body["documents_ready"] is True
    assert body["completed"] == 33
    results = {r["id"]: r for r in body["results"]}
    assert len(results) == 33

    # Injection cases are refused before any model call, in every language.
    for case in load_golden().cases:
        if case.category == "injection":
            assert results[case.id]["passed"], case.id
            assert results[case.id]["checks"]["no_prompt_leak"] is True
    # English out-of-scope: refusal template or no hits — both pass.
    for case in load_golden().cases:
        if case.category == "out_of_scope" and case.language == "en":
            assert results[case.id]["passed"], case.id
    # English grounded: a refusal never contains the facts nor citations.
    for case in load_golden().cases:
        if case.category == "grounded" and case.language == "en":
            assert not results[case.id]["passed"], case.id
            assert results[case.id]["checks"] == {"facts": False, "citations": False}

    summary = body["summary"]
    assert summary["total"] == 33
    assert summary["passed"] == sum(r["passed"] for r in body["results"])
    assert summary["per_language"]["en"]["total"] == 11
    assert summary["per_category"]["injection"] == {"total": 6, "passed": 6}

    # No conversations, messages, cache entries or visitor counters.
    async with get_session_factory()() as db:
        assert await db.scalar(select(func.count()).select_from(Conversation)) == 0
        assert await db.scalar(select(func.count()).select_from(Message)) == 0
    kv = get_kv_store()
    assert not [key for key in kv._data if key.startswith("chat:")]
    assert metrics.snapshot().get("chats_total", 0) == 0


async def test_eval_requires_owner_and_csrf(eval_client) -> None:
    session = await _owner_session(eval_client)
    response = await eval_client.post("/api/v1/dashboard/eval/run")
    assert response.status_code == 403  # missing CSRF
    response = await eval_client.post(
        "/api/v1/dashboard/users",
        json={"email": "eval-viewer@acme.com", "password": "viewer-password-1"},
        headers=_csrf(session["csrf"]),
    )
    assert response.status_code == 201, response.text
    await eval_client.post("/api/v1/auth/logout", headers=_csrf(session["csrf"]))
    response = await eval_client.post(
        "/api/v1/auth/login",
        json={"email": "eval-viewer@acme.com", "password": "viewer-password-1"},
    )
    viewer_csrf = response.json()["csrf_token"]
    response = await eval_client.post("/api/v1/dashboard/eval/run", headers=_csrf(viewer_csrf))
    assert response.status_code == 403
    assert "owner" in response.json()["detail"]
    # Viewers can still read results.
    assert (await eval_client.get("/api/v1/dashboard/eval")).status_code == 200


async def test_eval_unauthenticated_is_401(eval_client) -> None:
    assert (await eval_client.get("/api/v1/dashboard/eval")).status_code == 401
    assert (await eval_client.post("/api/v1/dashboard/eval/run")).status_code == 401


async def test_eval_conflicts_while_running_and_recovers_when_stale(eval_client) -> None:
    session = await _owner_session(eval_client)
    company_id = session["company"]["id"]
    kv = get_kv_store()
    fresh = {
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "total": 33,
        "completed": 0,
        "results": [],
    }
    await kv.set(f"eval:{company_id}", json.dumps(fresh))
    response = await eval_client.post("/api/v1/dashboard/eval/run", headers=_csrf(session["csrf"]))
    assert response.status_code == 409
    stale = dict(fresh, started_at=(datetime.now(UTC) - timedelta(minutes=31)).isoformat())
    await kv.set(f"eval:{company_id}", json.dumps(stale))
    response = await eval_client.post("/api/v1/dashboard/eval/run", headers=_csrf(session["csrf"]))
    assert response.status_code == 202, response.text


async def test_eval_state_is_scoped_per_company(eval_client, fake_llm) -> None:
    first = await _owner_session(eval_client, email="eval-first@acme.com")
    fake_llm.answers = [NO_ANSWER["en"]]
    response = await eval_client.post("/api/v1/dashboard/eval/run", headers=_csrf(first["csrf"]))
    assert response.status_code == 202
    await eval_client.post("/api/v1/auth/logout", headers=_csrf(first["csrf"]))
    await _owner_session(eval_client, email="eval-second@acme.com")
    body = (await eval_client.get("/api/v1/dashboard/eval")).json()
    assert body["status"] == "idle"
    assert body["documents_ready"] is False


async def test_eval_llm_failure_marks_run_failed_then_recovers(eval_client, fake_llm) -> None:
    session = await _owner_session(eval_client)
    await _upload_demo_docs(eval_client, session["company"]["api_key"])
    fake_llm.fail = True
    response = await eval_client.post("/api/v1/dashboard/eval/run", headers=_csrf(session["csrf"]))
    assert response.status_code == 202
    body = (await eval_client.get("/api/v1/dashboard/eval")).json()
    assert body["status"] == "failed"
    assert "model service is down" in body["error"]
    fake_llm.fail = False
    fake_llm.answers = [NO_ANSWER["en"]]
    response = await eval_client.post("/api/v1/dashboard/eval/run", headers=_csrf(session["csrf"]))
    assert response.status_code == 202
    body = (await eval_client.get("/api/v1/dashboard/eval")).json()
    assert body["status"] == "done"


async def test_eval_run_without_documents_refuses_grounded_cases(eval_client, fake_llm) -> None:
    session = await _owner_session(eval_client)
    fake_llm.answers = ["30 days [1]."]
    response = await eval_client.post("/api/v1/dashboard/eval/run", headers=_csrf(session["csrf"]))
    assert response.status_code == 202
    body = (await eval_client.get("/api/v1/dashboard/eval")).json()
    assert body["status"] == "done"
    assert body["documents_ready"] is False
    # Nothing to retrieve: every grounded case must fail, no model call needed.
    for result in body["results"]:
        if result["category"] == "grounded":
            assert not result["passed"]
    assert fake_llm.calls == []