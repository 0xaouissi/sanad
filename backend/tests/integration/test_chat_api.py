"""Grounded chat endpoint: auth, citations, don't-know rule, memory, language
retry, streaming metadata — real PostgreSQL, fake embeddings and scripted LLM."""

import json
import uuid

import pytest
from httpx import AsyncClient

from app.services.rag_chat import NO_ANSWER
from tests.integration.conftest import ScriptedLLM, auth, create_company, upload

POLICY = """# Refund policy
Customers may request a full refund within 30 days of purchase.

# Shipping policy
We ship worldwide. Standard delivery takes 5 to 7 business days.
"""

POLICY_FR = """# Politique de remboursement
Les clients peuvent demander un remboursement complet dans les 30 jours suivant l'achat.

# Politique de livraison
Nous livrons dans le monde entier. La livraison standard prend 5 a 7 jours ouvrables.
"""


def _events(text: str) -> list[dict]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


async def _company_with_policy(
    client: AsyncClient, text: str = POLICY, filename: str = "policy.md"
) -> dict:
    company = await create_company(client)
    await upload(client, company["api_key"], filename, text.encode())
    return company


async def test_chat_requires_api_key(client: AsyncClient) -> None:
    response = await client.post("/api/v1/chat", json={"message": "Hi"})
    assert response.status_code == 401


async def test_chat_rejects_blank_message(client: AsyncClient) -> None:
    company = await create_company(client)
    response = await client.post(
        "/api/v1/chat", json={"message": "   "}, headers=auth(company["api_key"])
    )
    assert response.status_code == 422


async def test_grounded_answer_with_citations(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client)
    fake_llm.answers = ["You can request a full refund within 30 days [1]."]
    response = await client.post(
        "/api/v1/chat",
        json={"message": "What is the refund policy?"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == fake_llm.answers[0]
    assert body["language"] == "en"
    assert body["model"] == "fake-model"
    assert body["provider"] == "fake"
    assert uuid.UUID(body["conversation_id"])
    assert body["citations"][0]["filename"] == "policy.md"
    assert body["citations"][0]["heading"] == "Refund policy"
    assert body["citations"][0]["index"] == 1
    system = fake_llm.calls[0][0]
    assert system.role == "system"
    assert "ONLY using the numbered sources" in system.content
    assert "policy.md" in system.content


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("What is the refund policy?", "en"),
        ("Quelle est la politique de remboursement ?", "fr"),
        ("ما هي سياسة الاسترجاع؟", "ar"),
    ],
)
async def test_no_documents_gives_localized_dont_know(
    client: AsyncClient, fake_llm: ScriptedLLM, question: str, language: str
) -> None:
    company = await create_company(client)
    response = await client.post(
        "/api/v1/chat", json={"message": question}, headers=auth(company["api_key"])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == NO_ANSWER[language]
    assert body["language"] == language
    assert body["citations"] == []
    assert fake_llm.calls == [], "LLM must not be called when there are no sources"


async def test_offtopic_question_below_threshold_refuses(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client)
    response = await client.post(
        "/api/v1/chat",
        json={"message": "qqqq xxxx zzzz vvvv"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200
    assert response.json()["answer"] == NO_ANSWER["en"]
    assert fake_llm.calls == []


async def test_llm_refusal_with_sources_is_canonical_and_uncited(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client)
    fake_llm.answers = [NO_ANSWER["en"] + " [1] [2]"]
    response = await client.post(
        "/api/v1/chat",
        json={"message": "What is the refund policy?"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(fake_llm.calls) == 1, "sources were retrieved, so the LLM must be called"
    assert body["answer"] == NO_ANSWER["en"]
    assert body["citations"] == [], "a refusal must not cite sources"


async def test_streamed_llm_refusal_has_no_citations(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client, POLICY_FR, "politique.md")
    fake_llm.answers = [NO_ANSWER["fr"] + " [1]"]
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Quelle est la politique de remboursement ?", "stream": True},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["type"] == "done"
    assert events[-1]["citations"] == []


async def test_conversation_memory_replays_history(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client)
    fake_llm.answers = ["Refunds take 30 days [1].", "Yes, that is correct [1]."]
    headers = auth(company["api_key"])
    first = await client.post(
        "/api/v1/chat", json={"message": "How long for a refund?"}, headers=headers
    )
    conversation_id = first.json()["conversation_id"]
    second = await client.post(
        "/api/v1/chat",
        json={
            "message": "Is the refund really within 30 days?",
            "conversation_id": conversation_id,
        },
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    history = fake_llm.calls[1]
    assert any(m.role == "user" and m.content == "How long for a refund?" for m in history)
    assert any(
        m.role == "assistant" and m.content == "Refunds take 30 days [1]." for m in history
    )


async def test_new_conversation_has_no_history(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client)
    headers = auth(company["api_key"])
    await client.post("/api/v1/chat", json={"message": "Refund policy details?"}, headers=headers)
    await client.post(
        "/api/v1/chat", json={"message": "Shipping delivery details?"}, headers=headers
    )
    assert len(fake_llm.calls[1]) == 2  # system + current question only


async def test_conversation_of_another_company_is_404(client: AsyncClient) -> None:
    owner = await _company_with_policy(client)
    stranger = await create_company(client, "Stranger")
    first = await client.post(
        "/api/v1/chat",
        json={"message": "Refund policy details?"},
        headers=auth(owner["api_key"]),
    )
    response = await client.post(
        "/api/v1/chat",
        json={
            "message": "Hello",
            "conversation_id": first.json()["conversation_id"],
        },
        headers=auth(stranger["api_key"]),
    )
    assert response.status_code == 404


async def test_unknown_conversation_is_404(client: AsyncClient) -> None:
    company = await create_company(client)
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Hello", "conversation_id": str(uuid.uuid4())},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 404


async def test_language_override_wins_over_detection(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client)
    fake_llm.answers = ["La politique de remboursement est de 30 jours [1]."]
    response = await client.post(
        "/api/v1/chat",
        json={"message": "What is the refund policy?", "language": "fr"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200
    assert response.json()["language"] == "fr"
    assert "French" in fake_llm.calls[0][0].content


async def test_wrong_language_answer_retried_once(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client, POLICY_FR, "politique.md")
    fake_llm.answers = [
        "You can request a refund within 30 days [1].",
        "Vous pouvez demander un remboursement sous 30 jours [1].",
    ]
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Quelle est la politique de remboursement ?"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["language"] == "fr"
    assert body["answer"] == fake_llm.answers[0]  # only the retry answer remains scripted
    assert len(fake_llm.calls) == 2
    assert "not written in French" in fake_llm.calls[1][-1].content


async def test_streaming_tokens_and_done_metadata(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client)
    fake_llm.answers = ["Refunds are possible within 30 days [1]."]
    response = await client.post(
        "/api/v1/chat",
        json={"message": "What is the refund policy?", "stream": True},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    answer = "".join(e["content"] for e in events if e["type"] == "token")
    assert answer.strip() == fake_llm.answers[0]
    done = events[-1]
    assert done["type"] == "done"
    assert done["language"] == "en"
    assert uuid.UUID(done["conversation_id"])
    assert done["citations"][0]["filename"] == "policy.md"


async def test_streaming_wrong_language_retried(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client, POLICY_FR, "politique.md")
    english = "This English answer is deliberately long so that the language check triggers. " * 3
    french = "Voici la réponse en français concernant le remboursement [1]."
    fake_llm.answers = [english, french]
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Quelle est la politique de remboursement ?", "stream": True},
        headers=auth(company["api_key"]),
    )
    events = _events(response.text)
    answer = "".join(e["content"] for e in events if e["type"] == "token")
    assert "réponse en français" in answer
    assert "deliberately long" not in answer
    assert len(fake_llm.calls) == 2
    assert events[-1]["type"] == "done"


async def test_streaming_dont_know_is_localized(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await create_company(client)
    response = await client.post(
        "/api/v1/chat",
        json={"message": "ما هي سياسة الاسترجاع؟", "stream": True},
        headers=auth(company["api_key"]),
    )
    events = _events(response.text)
    answer = "".join(e["content"] for e in events if e["type"] == "token")
    assert answer == NO_ANSWER["ar"]
    assert events[-1]["language"] == "ar"
    assert fake_llm.calls == []


async def test_provider_down_returns_503_with_hint(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client)
    fake_llm.fail = True
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Refund policy details?"},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 503
    assert "down" in response.json()["detail"]


async def test_stream_reports_error_event(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_policy(client)
    fake_llm.fail = True
    response = await client.post(
        "/api/v1/chat",
        json={"message": "Refund policy details?", "stream": True},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200
    events = _events(response.text)
    assert events[-1]["type"] == "error"
    assert "down" in events[-1]["detail"]