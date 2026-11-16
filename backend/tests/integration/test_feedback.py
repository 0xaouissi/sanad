"""Thumbs up/down feedback: company scoping, one rating per message, site-key path."""

import json
import uuid

from httpx import AsyncClient

from tests.integration.conftest import ScriptedLLM, auth, create_company, upload
from tests.integration.test_site_key import site_auth

POLICY = """# Refund policy
Customers may request a full refund within 30 days of purchase.
"""


async def _assistant_message(client: AsyncClient, fake_llm: ScriptedLLM) -> tuple[dict, str]:
    company = await create_company(client)
    await upload(client, company["api_key"], "policy.md", POLICY.encode())
    fake_llm.answers = ["You can request a refund within 30 days [1]."]
    response = await client.post(
        "/api/v1/chat",
        json={"message": "What is the refund policy?"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200, response.text
    return company, response.json()["message_id"]


async def test_chat_response_includes_message_id(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    _, message_id = await _assistant_message(client, fake_llm)
    assert uuid.UUID(message_id)


async def test_stream_done_includes_message_id(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await create_company(client)
    await upload(client, company["api_key"], "policy.md", POLICY.encode())
    fake_llm.answers = ["Refunds take 30 days [1]."]
    response = await client.post(
        "/api/v1/chat",
        json={"message": "What is the refund policy?", "stream": True},
        headers=auth(company["api_key"]),
    )
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    done = events[-1]
    assert done["type"] == "done"
    assert uuid.UUID(done["message_id"])


async def test_feedback_stores_rating(client: AsyncClient, fake_llm: ScriptedLLM) -> None:
    company, message_id = await _assistant_message(client, fake_llm)
    response = await client.post(
        "/api/v1/feedback",
        json={"message_id": message_id, "rating": "up"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["message_id"] == message_id
    assert body["rating"] == "up"
    assert uuid.UUID(body["id"])


async def test_feedback_rejects_duplicate_rating(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company, message_id = await _assistant_message(client, fake_llm)
    headers = auth(company["api_key"])
    first = await client.post(
        "/api/v1/feedback", json={"message_id": message_id, "rating": "up"}, headers=headers
    )
    assert first.status_code == 201
    second = await client.post(
        "/api/v1/feedback", json={"message_id": message_id, "rating": "down"}, headers=headers
    )
    assert second.status_code == 409


async def test_feedback_rejects_invalid_rating(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company, message_id = await _assistant_message(client, fake_llm)
    response = await client.post(
        "/api/v1/feedback",
        json={"message_id": message_id, "rating": "meh"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 422


async def test_feedback_for_other_company_message_is_404(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    _, message_id = await _assistant_message(client, fake_llm)
    stranger = await create_company(client, "Stranger")
    response = await client.post(
        "/api/v1/feedback",
        json={"message_id": message_id, "rating": "down"},
        headers=auth(stranger["api_key"]),
    )
    assert response.status_code == 404


async def test_feedback_for_unknown_message_is_404(client: AsyncClient) -> None:
    company = await create_company(client)
    response = await client.post(
        "/api/v1/feedback",
        json={"message_id": str(uuid.uuid4()), "rating": "up"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 404


async def test_feedback_requires_credentials(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/feedback", json={"message_id": str(uuid.uuid4()), "rating": "up"}
    )
    assert response.status_code == 401


async def test_feedback_with_site_key_from_allowed_origin(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company, message_id = await _assistant_message(client, fake_llm)
    update = await client.put(
        "/api/v1/companies/domains",
        json={"domains": ["acme.com"]},
        headers=auth(company["api_key"]),
    )
    assert update.status_code == 200
    response = await client.post(
        "/api/v1/feedback",
        json={"message_id": message_id, "rating": "down"},
        headers=site_auth(company["site_key"], "https://acme.com"),
    )
    assert response.status_code == 201, response.text
    assert response.json()["rating"] == "down"


async def test_feedback_with_site_key_from_other_origin_is_403(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company, message_id = await _assistant_message(client, fake_llm)
    await client.put(
        "/api/v1/companies/domains",
        json={"domains": ["acme.com"]},
        headers=auth(company["api_key"]),
    )
    response = await client.post(
        "/api/v1/feedback",
        json={"message_id": message_id, "rating": "up"},
        headers=site_auth(company["site_key"], "https://evil.com"),
    )
    assert response.status_code == 403


async def test_widget_script_is_served_without_auth(client: AsyncClient) -> None:
    response = await client.get("/widget.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/javascript")
    assert "sanad" in response.text.lower()
    assert ".innerHTML" not in response.text
    assert "insertAdjacentHTML" not in response.text
    assert "document.write" not in response.text