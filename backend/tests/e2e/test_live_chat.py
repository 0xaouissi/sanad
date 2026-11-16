"""Step 3 acceptance: grounded live chat in ar/fr/en — real Ollama, real BGE-M3.

Answers must come from the uploaded document, carry citations, and be written
in the visitor's language. Out-of-scope questions (5 per language) must be
refused with the localized "I don't know" + contact offer. The threshold
separation test pins the calibration of RETRIEVAL_MIN_SCORE on real scores.
"""

import json
import time

import pytest
from httpx import AsyncClient

from app.core.config import Settings, get_settings
from app.core.security import company_for_api_key
from app.db.session import get_session_factory
from app.providers.embeddings import get_embedding_provider
from app.providers.llm.base import LLMError
from app.providers.llm.ollama import OllamaProvider
from app.rag.retrieval import retrieve
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

POLICY_FR = """# Politique de remboursement
Les clients peuvent demander un remboursement complet dans les 30 jours suivant
l'achat. Le remboursement est effectue sous 5 jours ouvrables.

# Politique de livraison
Nous livrons dans le monde entier. La livraison standard prend 5 a 7 jours ouvrables.
"""

POLICY_AR = """# سياسة الاسترجاع
يحق للعميل طلب استرجاع كامل المبلغ خلال ثلاثين يوما من تاريخ الشراء. يتم رد المبلغ
خلال خمسة أيام عمل إلى وسيلة الدفع الأصلية.

# سياسة الشحن
نشحن إلى جميع أنحاء العالم. يستغرق التوصيل العادي من خمسة إلى سبعة أيام عمل.
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

# Real BGE-M3 best-hit cosine scores against the trilingual corpus (calibration
# 2026-11-16): in-scope 0.4549..0.7936, off-topic 0.2332..0.3927. The default
# RETRIEVAL_MIN_SCORE=0.43 sits in that gap. The two lowest in-scope queries
# (fr privacy 0.4998, ar shipping 0.4549) were falsely refused at the old 0.55.
IN_SCOPE = [
    ("en", "How many days do I have to request a refund?"),
    ("en", "How long does standard delivery take?"),
    ("fr", "Combien de jours ai-je pour demander un remboursement ?"),
    ("fr", "Quelle est la politique de confidentialité ?"),
    ("ar", "كم يوما لدي لطلب استرجاع المبلغ؟"),
    ("ar", "ما هي سياسة الشحن؟"),
]

OFF_TOPIC = [
    ("en", "What is the capital of France?"),
    ("en", "What will the weather be like tomorrow in Tokyo?"),
    ("fr", "Quelle est la capitale de la France ?"),
    ("fr", "Quel temps fera-t-il demain à Tokyo ?"),
    ("ar", "ما هي عاصمة فرنسا؟"),
    ("ar", "كيف سيكون الطقس غدا في طوكيو؟"),
]

# Business questions the documents do not cover. They score ABOVE the threshold
# (0.47..0.50), so retrieval passes them to the LLM, whose grounding rule must
# refuse them. Verified live: the 3B replies with the exact localized template.
NEAR_MISS = {
    "en": ["Do you sell gift cards?", "What are your opening hours?"],
    "fr": ["Vendez-vous des cartes cadeaux ?", "Quels sont vos horaires d'ouverture ?"],
    "ar": ["هل تبيعون بطاقات الهدايا؟", "ما هي ساعات العمل لديكم؟"],
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


async def _company_with_trilingual_policies(client: AsyncClient) -> str:
    company = await make_company(client)
    for filename, text in [
        ("policy-en.md", POLICY_EN),
        ("policy-fr.md", POLICY_FR),
        ("policy-ar.md", POLICY_AR),
    ]:
        await upload_and_wait(client, company["api_key"], filename, text.encode())
    return company["api_key"]


async def test_threshold_separates_in_scope_from_off_topic(live_rag: AsyncClient) -> None:
    api_key = await _company_with_trilingual_policies(live_rag)
    settings = get_settings()
    embedder = get_embedding_provider()
    async with get_session_factory()() as session:
        company = await company_for_api_key(session, api_key)
        for lang, question in IN_SCOPE:
            hits = await retrieve(session, company.id, question, embedder, settings, None)
            assert hits, f"in-scope question refused by retrieval: [{lang}] {question}"
            assert hits[0].score >= settings.retrieval_min_score
        for lang, question in OFF_TOPIC:
            hits = await retrieve(session, company.id, question, embedder, settings, None)
            assert hits == [], f"off-topic question passed retrieval: [{lang}] {question}"


@pytest.mark.parametrize("lang", ["en", "fr", "ar"])
async def test_near_miss_questions_refused_by_grounding_rule(
    live_rag: AsyncClient, lang: str
) -> None:
    api_key = await _company_with_trilingual_policies(live_rag)
    for question in NEAR_MISS[lang]:
        response = await live_rag.post(
            "/api/v1/chat", json={"message": question}, headers={"X-API-Key": api_key}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["language"] == lang, question
        assert body["answer"] == NO_ANSWER[lang], f"{question!r} -> {body['answer']!r}"
        assert body["citations"] == [], f"refusal must not cite sources: {question!r}"