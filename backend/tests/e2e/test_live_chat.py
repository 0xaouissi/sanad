"""Step 3 acceptance: grounded live chat in ar/fr/en — real Ollama, real BGE-M3.

Answers must come from the uploaded document, carry citations, and be written
in the visitor's language. Out-of-scope questions (5 per language) must be
refused with the localized "I don't know" + contact offer.
"""

import json
import time

import pytest
from httpx import AsyncClient

from app.core.config import Settings, get_settings
from app.providers.llm.base import LLMError
from app.providers.llm.ollama import OllamaProvider
from app.services.rag_chat import NO_ANSWER
from tests.e2e.conftest import make_company, upload_and_wait

POLICY_EN = """# Refund policy
Customers may request a full refund within 30 days of purchase. Refunds are issued
to the original payment method within 5 business days.

# Shipping policy
We ship worldwide. Standard delivery takes 5 to 7 business days and includes tracking.

# Privacy policy
We never sell customer data. Contact privacy@acme.example to request data deletion.
"""

GROUNDED_CASES = [
    ("en", "How many days do I have to request a refund?"),
    ("fr", "Combien de jours ai-je pour demander un remboursement ?"),
    ("ar", "كم يوما لدي لطلب استرجاع المبلغ؟"),
]

OUT_OF_SCOPE = {
    "en": [
        "What is the capital of France?",
        "Who won the 2022 FIFA World Cup?",
        "How do I cook couscous for four people?",
        "What will the weather be like tomorrow in Tokyo?",
        "How can I train a puppy to sit?",
    ],
    "fr": [
        "Quelle est la capitale de la France ?",
        "Qui a gagné la Coupe du monde 2022 ?",
        "Comment préparer un couscous pour quatre personnes ?",
        "Quel temps fera-t-il demain à Tokyo ?",
        "Comment dresser un chiot à s'asseoir ?",
    ],
    "ar": [
        "ما هي عاصمة فرنسا؟",
        "من فاز بكأس العالم 2022؟",
        "كيف أطبخ الكسكسي لأربعة أشخاص؟",
        "كيف سيكون الطقس غدا في طوكيو؟",
        "كيف أدرب جروا على الجلوس؟",
    ],
}


@pytest.fixture(autouse=True)
async def _ollama_up():
    provider = OllamaProvider(Settings())
    try:
        await provider.health()
    except LLMError as exc:
        pytest.skip(f"Live Ollama unavailable: {exc}")
    finally:
        await provider.aclose()


def _has_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


async def _company_with_policy(client: AsyncClient) -> str:
    company = await make_company(client)
    await upload_and_wait(client, company["api_key"], "policy-en.md", POLICY_EN.encode())
    return company["api_key"]


@pytest.mark.parametrize(("lang", "question"), GROUNDED_CASES)
async def test_grounded_answer_in_visitor_language(
    live_rag: AsyncClient, lang: str, question: str
) -> None:
    api_key = await _company_with_policy(live_rag)
    response = await live_rag.post(
        "/api/v1/chat", json={"message": question}, headers={"X-API-Key": api_key}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["language"] == lang
    assert body["answer"].strip()
    assert body["answer"] != NO_ANSWER[lang]
    assert body["citations"], "grounded answer must cite the document"
    assert body["citations"][0]["filename"] == "policy-en.md"
    if lang == "ar":
        assert _has_arabic(body["answer"]), body["answer"]
    else:
        assert not _has_arabic(body["answer"]), body["answer"]
        assert any(ch.isascii() and ch.isalpha() for ch in body["answer"])


async def test_stream_first_token_within_tier_budget(live_rag: AsyncClient) -> None:
    api_key = await _company_with_policy(live_rag)
    budget_s = get_settings().first_token_budget_s
    started = time.perf_counter()
    first_token_s: float | None = None
    events: list[dict] = []
    async with live_rag.stream(
        "POST",
        "/api/v1/chat",
        json={"message": "What is the refund policy?", "stream": True},
        headers={"X-API-Key": api_key},
    ) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line.removeprefix("data: "))
            events.append(event)
            if event["type"] == "token" and first_token_s is None:
                first_token_s = time.perf_counter() - started
    assert first_token_s is not None, "no token events"
    assert first_token_s <= budget_s, f"first token {first_token_s:.2f}s > budget {budget_s}s"
    done = events[-1]
    assert done["type"] == "done"
    assert done["language"] == "en"
    assert done["citations"][0]["filename"] == "policy-en.md"
    assert done["conversation_id"]


@pytest.mark.parametrize("lang", ["en", "fr", "ar"])
async def test_out_of_scope_questions_refused(live_rag: AsyncClient, lang: str) -> None:
    api_key = await _company_with_policy(live_rag)
    for question in OUT_OF_SCOPE[lang]:
        response = await live_rag.post(
            "/api/v1/chat", json={"message": question}, headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["language"] == lang, question
        assert body["answer"] == NO_ANSWER[lang], f"{question!r} -> {body['answer']!r}"
        assert body["citations"] == [], question


async def test_followup_question_uses_conversation_memory(live_rag: AsyncClient) -> None:
    api_key = await _company_with_policy(live_rag)
    headers = {"X-API-Key": api_key}
    first = await live_rag.post(
        "/api/v1/chat",
        json={"message": "How many days do I have to request a refund?"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]
    second = await live_rag.post(
        "/api/v1/chat",
        json={
            "message": "And how long does the refund take to arrive?",
            "conversation_id": conversation_id,
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["conversation_id"] == conversation_id
    assert body["answer"] != NO_ANSWER["en"]
    assert body["citations"], "follow-up must still be grounded"