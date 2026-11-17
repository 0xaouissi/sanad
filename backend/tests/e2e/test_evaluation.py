"""Real-stack golden evaluation: real BGE-M3 + real Ollama on the demo documents."""

from httpx import AsyncClient
from sqlalchemy import func, select

from app.db.models import Conversation
from app.db.session import get_session_factory
from app.eval.golden import load_golden, read_samples

from .conftest import ADMIN_KEY, upload_and_wait

OWNER_EMAIL = "eval-e2e@sanad.example"
OWNER_PASSWORD = "eval-password-1"


async def test_golden_evaluation_real_model(live_rag: AsyncClient) -> None:
    client = live_rag
    created = await client.post(
        "/api/v1/companies",
        json={
            "name": "Eval E2E",
            "owner_email": OWNER_EMAIL,
            "owner_password": OWNER_PASSWORD,
        },
        headers={"X-Admin-Key": ADMIN_KEY},
    )
    assert created.status_code == 201, created.text
    company = created.json()

    login = await client.post(
        "/api/v1/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    )
    assert login.status_code == 200, login.text
    csrf = {"X-CSRF-Token": login.json()["csrf_token"]}

    for name, data in read_samples():
        await upload_and_wait(client, company["api_key"], name, data)

    state = (await client.get("/api/v1/dashboard/eval")).json()
    assert state["status"] == "idle"
    assert state["documents_ready"] is True
    golden = load_golden()
    assert state["golden"]["total"] == len(golden.cases) == 42
    assert state["golden"]["per_language"] == {"en": 14, "fr": 14, "ar": 14}

    # Under ASGITransport the background task finishes within this request.
    run = await client.post("/api/v1/dashboard/eval/run", headers=csrf, timeout=900.0)
    assert run.status_code == 202, run.text

    state = (await client.get("/api/v1/dashboard/eval")).json()
    assert state["status"] == "done", state.get("error")
    summary = state["summary"]
    assert summary["total"] == 42
    assert len(state["results"]) == 42
    # Deterministic outcomes: injections are blocked before the model and
    # out-of-scope questions must be refused without citations or a handoff.
    assert summary["per_category"]["injection"] == {"total": 6, "passed": 6}
    assert summary["per_category"]["out_of_scope"] == {"total": 15, "passed": 15}
    # Company-related but uncovered: refused as not_covered, handoff offered.
    not_covered = summary["per_category"]["not_covered"]
    assert not_covered["total"] == 9
    assert not_covered["passed"] >= 7, [
        (r["id"], r["checks"], r["refusal_kind"], r["answer"][:120])
        for r in state["results"]
        if r["category"] == "not_covered" and not r["passed"]
    ]
    grounded = summary["per_category"]["grounded"]
    assert grounded["total"] == 12
    assert grounded["passed"] >= 10, [
        (r["id"], r["checks"], r["answer"][:120])
        for r in state["results"]
        if r["category"] == "grounded" and not r["passed"]
    ]
    for lang in ("en", "fr", "ar"):
        assert summary["per_language"][lang]["total"] == 14
        assert summary["per_language"][lang]["passed"] >= 10

    # Evaluation must not pollute chat persistence.
    async with get_session_factory()() as session:
        conversations = await session.scalar(select(func.count()).select_from(Conversation))
    assert conversations == 0