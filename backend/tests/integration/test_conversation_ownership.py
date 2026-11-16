"""Conversation IDs are unguessable UUID4 and usable only by their company."""

import json
import uuid

from tests.integration.conftest import auth, create_company


async def _start_conversation(client, api_key) -> str:
    response = await client.post(
        "/api/v1/chat", json={"message": "What is the refund policy?"},
        headers=auth(api_key),
    )
    assert response.status_code == 200, response.text
    return response.json()["conversation_id"]


async def test_conversation_ids_are_uuid4(client):
    company = await create_company(client)
    conversation_id = await _start_conversation(client, company["api_key"])
    parsed = uuid.UUID(conversation_id)
    assert parsed.version == 4
    assert str(parsed) == conversation_id


async def test_other_company_cannot_use_conversation(client):
    owner = await create_company(client, "Owner")
    attacker = await create_company(client, "Attacker")
    conversation_id = await _start_conversation(client, owner["api_key"])
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Tell me more", "conversation_id": conversation_id},
        headers=auth(attacker["api_key"]),
    )
    assert response.status_code == 404


async def test_random_conversation_id_is_rejected(client):
    company = await create_company(client)
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Hello", "conversation_id": str(uuid.uuid4())},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 404


async def test_owner_can_continue_conversation(client, fake_llm):
    company = await create_company(client)
    fake_llm.answers = ["First. [1]", "Second. [1]"]
    conversation_id = await _start_conversation(client, company["api_key"])
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Tell me more", "conversation_id": conversation_id},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["conversation_id"] == conversation_id


async def test_streamed_foreign_conversation_yields_error(client):
    owner = await create_company(client, "Owner")
    attacker = await create_company(client, "Attacker")
    conversation_id = await _start_conversation(client, owner["api_key"])
    async with client.stream(
        "POST",
        "/api/v1/chat",
        json={
            "message": "Tell me more",
            "conversation_id": conversation_id,
            "stream": True,
        },
        headers=auth(attacker["api_key"]),
    ) as response:
        assert response.status_code == 200
        events = [
            json.loads(line[6:])
            async for line in response.aiter_lines()
            if line.startswith("data: ")
        ]
    assert events[-1]["type"] == "error"
    assert not any(e["type"] == "token" for e in events)