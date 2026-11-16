"""Similarity search endpoint (fake deterministic embeddings, real pgvector)."""

from tests.integration.conftest import auth, create_company, get_document, upload

REFUNDS = "Refund policy. Customers may request a refund within 30 days of purchase."
SHIPPING = "Shipping policy. We ship worldwide within 5 business days with tracking."


async def test_search_ranks_relevant_chunk_first(client):
    company = await create_company(client)
    await upload(client, company["api_key"], "refunds.txt", REFUNDS.encode())
    await upload(client, company["api_key"], "shipping.txt", SHIPPING.encode())
    response = await client.post(
        "/api/v1/search",
        json={"query": "how do I get a refund", "top_k": 2},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200
    hits = response.json()["hits"]
    assert len(hits) == 2
    assert hits[0]["filename"] == "refunds.txt"
    assert hits[0]["score"] >= hits[1]["score"]
    assert "refund" in hits[0]["content"].lower()


async def test_search_returns_metadata(client):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "refunds.txt", REFUNDS.encode())
    await get_document(client, company["api_key"], doc["id"])
    response = await client.post(
        "/api/v1/search", json={"query": "refund"}, headers=auth(company["api_key"])
    )
    hit = response.json()["hits"][0]
    assert hit["document_id"] == doc["id"]
    assert hit["chunk_id"]
    assert "page_number" in hit and "heading" in hit


async def test_search_top_k_limit(client):
    company = await create_company(client)
    long_text = "\n\n".join(f"Section {i} about refund number {i}." for i in range(20))
    await upload(client, company["api_key"], "long.txt", long_text.encode())
    response = await client.post(
        "/api/v1/search",
        json={"query": "refund", "top_k": 3},
        headers=auth(company["api_key"]),
    )
    assert len(response.json()["hits"]) == 3


async def test_search_blank_query_422(client):
    company = await create_company(client)
    response = await client.post(
        "/api/v1/search", json={"query": "   "}, headers=auth(company["api_key"])
    )
    assert response.status_code == 422


async def test_search_empty_company_no_hits(client):
    company = await create_company(client)
    response = await client.post(
        "/api/v1/search", json={"query": "anything"}, headers=auth(company["api_key"])
    )
    assert response.status_code == 200
    assert response.json()["hits"] == []