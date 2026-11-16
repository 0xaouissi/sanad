"""Hybrid retrieval against real PostgreSQL: dense + keyword fusion, threshold,
company isolation, and reranker wiring (fake cross-encoder)."""

from app.core.config import get_settings
from app.core.security import company_for_api_key
from app.db.session import get_session_factory
from app.providers.reranker.base import RerankProvider
from app.rag.retrieval import retrieve
from tests.integration.conftest import FakeEmbedder, create_company, upload

POLICY = """# Refund policy
Customers may request a full refund within 30 days of purchase.

# Shipping policy
We ship worldwide. Standard delivery takes 5 to 7 business days.
"""


class FakeReranker(RerankProvider):
    name = "fake"
    model = "fake-reranker"

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        self.calls.append((query, list(documents)))
        return [0.9 if "refund" in doc.lower() else 0.2 for doc in documents]


async def _company_with_policy(client) -> str:
    company = await create_company(client)
    await upload(client, company["api_key"], "policy.md", POLICY.encode())
    return company["api_key"]


async def _owner_id(api_key: str):
    async with get_session_factory()() as session:
        company = await company_for_api_key(session, api_key)
        return company.id


async def test_dense_match_returns_relevant_chunk(client) -> None:
    api_key = await _company_with_policy(client)
    async with get_session_factory()() as session:
        hits = await retrieve(
            session, await _owner_id(api_key), "refund within 30 days",
            FakeEmbedder(), get_settings(),
        )
    assert hits
    assert hits[0].heading == "Refund policy"
    assert hits[0].filename == "policy.md"
    assert hits[0].score >= get_settings().retrieval_min_score


async def test_keyword_search_rescues_exact_term(client) -> None:
    api_key = await _company_with_policy(client)
    await upload(client, api_key, "zebra.md", b"The zebra crossing rules apply here.")
    async with get_session_factory()() as session:
        hits = await retrieve(
            session, await _owner_id(api_key), "zebra crossing", FakeEmbedder(), get_settings()
        )
    assert any("zebra" in hit.content.lower() for hit in hits)


async def test_unrelated_query_below_threshold_returns_nothing(client) -> None:
    api_key = await _company_with_policy(client)
    async with get_session_factory()() as session:
        hits = await retrieve(
            session, await _owner_id(api_key), "qqqq xxxx zzzz",
            FakeEmbedder(), get_settings(),
        )
    assert hits == []


async def test_other_company_chunks_are_invisible(client) -> None:
    await _company_with_policy(client)
    other = await create_company(client, "Other")
    async with get_session_factory()() as session:
        hits = await retrieve(
            session, await _owner_id(other["api_key"]), "refund",
            FakeEmbedder(), get_settings(),
        )
    assert hits == []


async def test_reranker_rescores_and_reorders(client) -> None:
    api_key = await _company_with_policy(client)
    reranker = FakeReranker()
    async with get_session_factory()() as session:
        hits = await retrieve(
            session, await _owner_id(api_key), "shipping delivery",
            FakeEmbedder(), get_settings(), reranker,
        )
    assert reranker.calls, "reranker was not called"
    assert hits[0].heading == "Refund policy"
    assert hits[0].score == 0.9
    assert all(hit.score >= get_settings().retrieval_min_score for hit in hits)