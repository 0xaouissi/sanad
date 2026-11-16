"""Dashboard data API: documents, failed questions, ratings, settings, key
rotation, export, deletion and the conversation-storage privacy toggle."""

import json
import uuid

from sqlalchemy import func, select

from app.db.models import Conversation, Feedback
from app.db.session import get_session_factory
from app.providers.kv import get_kv_store
from tests.integration.conftest import ADMIN_KEY, auth, create_company
from tests.integration.test_dashboard_auth import create_company_with_owner, login

POLICY = """# Refund policy
Customers may request a full refund within 30 days of purchase.
"""


async def _owner_session(client, name: str = "Acme", email: str = "owner@acme.com"):
    company = await create_company_with_owner(client, name=name, email=email)
    csrf = (await login(client, email=email)).json()["csrf_token"]
    return company, csrf


def csrf_headers(csrf: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf}


async def _chat(client, api_key: str, message: str, **extra):
    return await client.post(
        "/api/v1/chat", json={"message": message, **extra}, headers=auth(api_key)
    )


async def test_document_upload_list_delete_through_dashboard(client) -> None:
    company, csrf = await _owner_session(client)
    uploaded = await client.post(
        "/api/v1/dashboard/documents",
        files={"file": ("policy.md", POLICY.encode())},
        headers=csrf_headers(csrf),
    )
    assert uploaded.status_code == 202, uploaded.text
    listed = await client.get("/api/v1/dashboard/documents")
    assert listed.status_code == 200
    docs = listed.json()
    assert len(docs) == 1
    assert docs[0]["filename"] == "policy.md"
    assert docs[0]["status"] == "ready"

    no_csrf = await client.delete(f"/api/v1/dashboard/documents/{docs[0]['id']}")
    assert no_csrf.status_code == 403
    deleted = await client.delete(
        f"/api/v1/dashboard/documents/{docs[0]['id']}", headers=csrf_headers(csrf)
    )
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/dashboard/documents")).json() == []


async def test_viewer_can_list_but_not_mutate_documents(client) -> None:
    _, owner_csrf = await _owner_session(client)
    await client.post(
        "/api/v1/dashboard/documents",
        files={"file": ("policy.md", POLICY.encode())},
        headers=csrf_headers(owner_csrf),
    )
    await client.post(
        "/api/v1/dashboard/users",
        json={"email": "viewer@acme.com", "password": "viewer-password-1"},
        headers=csrf_headers(owner_csrf),
    )
    viewer_csrf = (
        await login(client, email="viewer@acme.com", password="viewer-password-1")
    ).json()["csrf_token"]
    listed = await client.get("/api/v1/dashboard/documents")
    assert listed.status_code == 200
    doc_id = listed.json()[0]["id"]
    assert (
        await client.post(
            "/api/v1/dashboard/documents",
            files={"file": ("more.md", b"# More\nOther text.")},
            headers=csrf_headers(viewer_csrf),
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/dashboard/documents/{doc_id}", headers=csrf_headers(viewer_csrf)
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/dashboard/documents/{doc_id}/reindex", headers=csrf_headers(viewer_csrf)
        )
    ).status_code == 403


async def test_failed_questions_lists_refusals_with_the_question(client) -> None:
    company, _ = await _owner_session(client)
    await client.post(
        "/api/v1/dashboard/documents",
        files={"file": ("policy.md", POLICY.encode())},
        headers=csrf_headers((await login(client)).json()["csrf_token"]),
    )
    grounded = await _chat(client, company["api_key"], "What is the refund policy?")
    assert grounded.status_code == 200
    refused = await _chat(client, company["api_key"], "qqq zzz unrelated nonsense xyz")
    assert refused.status_code == 200
    assert refused.json()["citations"] == []

    failed = await client.get("/api/v1/dashboard/failed-questions")
    assert failed.status_code == 200
    items = failed.json()
    assert len(items) == 1
    assert items[0]["question"] == "qqq zzz unrelated nonsense xyz"
    assert items[0]["message_id"] == refused.json()["message_id"]


async def test_ratings_shows_feedback_with_question_and_answer(client) -> None:
    company, _ = await _owner_session(client)
    await client.post(
        "/api/v1/dashboard/documents",
        files={"file": ("policy.md", POLICY.encode())},
        headers=csrf_headers((await login(client)).json()["csrf_token"]),
    )
    answer = await _chat(client, company["api_key"], "What is the refund policy?")
    message_id = answer.json()["message_id"]
    rated = await client.post(
        "/api/v1/feedback",
        json={"message_id": message_id, "rating": "up"},
        headers=auth(company["api_key"]),
    )
    assert rated.status_code == 201, rated.text
    summary = await client.get("/api/v1/dashboard/ratings")
    assert summary.status_code == 200
    body = summary.json()
    assert body["up"] == 1
    assert body["down"] == 0
    assert body["items"][0]["question"] == "What is the refund policy?"
    assert body["items"][0]["answer"]


async def test_settings_get_and_update(client) -> None:
    _, csrf = await _owner_session(client)
    settings = await client.get("/api/v1/dashboard/settings")
    assert settings.status_code == 200
    body = settings.json()
    assert body["store_conversations"] is True
    assert body["allowed_domains"] == []
    assert body["site_key"].startswith("pk-")

    updated = await client.put(
        "/api/v1/dashboard/settings",
        json={"allowed_domains": ["acme.com", "*.acme.com"], "store_conversations": False},
        headers=csrf_headers(csrf),
    )
    assert updated.status_code == 200
    assert updated.json()["allowed_domains"] == ["acme.com", "*.acme.com"]
    assert updated.json()["store_conversations"] is False
    assert (await client.get("/api/v1/dashboard/settings")).json()["store_conversations"] is False

    bad = await client.put(
        "/api/v1/dashboard/settings",
        json={"allowed_domains": ["https://bad.example/path"]},
        headers=csrf_headers(csrf),
    )
    assert bad.status_code == 422
    assert (
        await client.put(
            "/api/v1/dashboard/settings", json={"store_conversations": True}
        )
    ).status_code == 403


async def test_privacy_toggle_stops_persistence_and_cache(client) -> None:
    company, csrf = await _owner_session(client)
    await client.put(
        "/api/v1/dashboard/settings",
        json={"store_conversations": False},
        headers=csrf_headers(csrf),
    )
    await client.post(
        "/api/v1/dashboard/documents",
        files={"file": ("policy.md", POLICY.encode())},
        headers=csrf_headers(csrf),
    )
    answer = await _chat(client, company["api_key"], "What is the refund policy?")
    assert answer.status_code == 200
    body = answer.json()
    assert body["answer"]
    assert body["conversation_id"] is None
    assert body["message_id"] is None

    async with get_session_factory()() as session:
        count = await session.scalar(select(func.count()).select_from(Conversation))
    assert count == 0
    kv = get_kv_store()
    keys = [k for k in getattr(kv, "_data", {}) if k.startswith("chat:")]
    assert keys == []

    streamed = await client.post(
        "/api/v1/chat",
        json={"message": "What is the refund policy?", "stream": True},
        headers=auth(company["api_key"]),
    )
    events = [
        json.loads(line.removeprefix("data: "))
        for line in streamed.text.splitlines()
        if line.startswith("data: ")
    ]
    done = next(e for e in events if e["type"] == "done")
    assert done["conversation_id"] is None
    assert done["message_id"] is None

    stale = await _chat(
        client, company["api_key"], "What is the refund policy?", conversation_id=str(uuid.uuid4())
    )
    assert stale.status_code == 404


async def test_key_rotation_invalidates_old_keys(client) -> None:
    company, csrf = await _owner_session(client)
    rotated = await client.post("/api/v1/dashboard/keys/rotate", headers=csrf_headers(csrf))
    assert rotated.status_code == 200, rotated.text
    keys = rotated.json()
    assert keys["api_key"].startswith("sk-")
    assert keys["site_key"].startswith("pk-")
    assert keys["api_key"] != company["api_key"]
    assert keys["site_key"] != company["site_key"]

    old = await client.get("/api/v1/documents", headers=auth(company["api_key"]))
    assert old.status_code == 401
    new = await client.get("/api/v1/documents", headers=auth(keys["api_key"]))
    assert new.status_code == 200
    assert (
        await client.post("/api/v1/dashboard/keys/rotate")
    ).status_code == 403


async def test_export_contains_company_data(client) -> None:
    company, csrf = await _owner_session(client)
    await client.post(
        "/api/v1/dashboard/documents",
        files={"file": ("policy.md", POLICY.encode())},
        headers=csrf_headers(csrf),
    )
    answer = await _chat(client, company["api_key"], "What is the refund policy?")
    await client.post(
        "/api/v1/feedback",
        json={"message_id": answer.json()["message_id"], "rating": "down"},
        headers=auth(company["api_key"]),
    )
    export = await client.get("/api/v1/dashboard/export")
    assert export.status_code == 200
    assert "attachment" in export.headers["content-disposition"]
    payload = export.json()
    assert payload["company"]["id"] == company["id"]
    assert payload["documents"][0]["filename"] == "policy.md"
    assert payload["conversations"][0]["messages"]
    assert payload["feedback"][0]["rating"] == "down"
    assert "api_key" not in json.dumps(payload)
    assert "password" not in json.dumps(payload)


async def test_delete_all_conversations(client) -> None:
    company, csrf = await _owner_session(client)
    await client.post(
        "/api/v1/dashboard/documents",
        files={"file": ("policy.md", POLICY.encode())},
        headers=csrf_headers(csrf),
    )
    answer = await _chat(client, company["api_key"], "What is the refund policy?")
    await client.post(
        "/api/v1/feedback",
        json={"message_id": answer.json()["message_id"], "rating": "up"},
        headers=auth(company["api_key"]),
    )
    assert (await client.delete("/api/v1/dashboard/conversations")).status_code == 403
    deleted = await client.delete(
        "/api/v1/dashboard/conversations", headers=csrf_headers(csrf)
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == 1
    assert (await client.get("/api/v1/dashboard/failed-questions")).json() == []
    assert (await client.get("/api/v1/dashboard/ratings")).json()["items"] == []
    async with get_session_factory()() as session:
        assert (await session.scalar(select(func.count()).select_from(Feedback))) == 0


async def test_dashboard_is_company_scoped(client) -> None:
    acme, acme_csrf = await _owner_session(client, name="Acme", email="owner@acme.com")
    await client.post(
        "/api/v1/dashboard/documents",
        files={"file": ("policy.md", POLICY.encode())},
        headers=csrf_headers(acme_csrf),
    )
    acme_doc_id = (await client.get("/api/v1/dashboard/documents")).json()[0]["id"]

    other, other_csrf = await _owner_session(client, name="Other", email="owner@other.com")
    assert (await client.get("/api/v1/dashboard/documents")).json() == []
    assert (await client.get("/api/v1/dashboard/settings")).json()["company_name"] == "Other"
    foreign = await client.delete(
        f"/api/v1/dashboard/documents/{acme_doc_id}", headers=csrf_headers(other_csrf)
    )
    assert foreign.status_code == 404
    assert other["id"] != acme["id"]


async def test_dashboard_requires_login(client) -> None:
    await create_company(client)
    for method, path in [
        ("GET", "/api/v1/dashboard/documents"),
        ("GET", "/api/v1/dashboard/failed-questions"),
        ("GET", "/api/v1/dashboard/ratings"),
        ("GET", "/api/v1/dashboard/settings"),
        ("GET", "/api/v1/dashboard/export"),
    ]:
        assert (await client.request(method, path)).status_code == 401
    assert (
        await client.post(
            "/api/v1/companies", json={"name": "X"}, headers={"X-Admin-Key": ADMIN_KEY}
        )
    ).status_code == 201