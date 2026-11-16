"""Upload, ingestion status, dedup, list, delete, reindex, isolation."""

import io

from docx import Document as DocxDocument

from tests.integration.conftest import auth, create_company, get_document, upload
from tests.pdf_builder import make_pdf

POLICY = (
    "Refund policy. Customers may request a refund within 30 days of purchase. "
    "Shipping policy. We ship worldwide within 5 business days."
)


async def test_upload_txt_ingests_to_ready(client):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.txt", POLICY.encode())
    assert doc["status"] == "pending"
    final = await get_document(client, company["api_key"], doc["id"])
    assert final["status"] == "ready", final["error"]
    assert final["chunk_count"] >= 1
    assert final["error"] is None


async def test_upload_pdf_with_pages(client):
    company = await create_company(client)
    data = make_pdf(["Refund policy page one", "Shipping policy page two"])
    doc = await upload(client, company["api_key"], "policy.pdf", data)
    final = await get_document(client, company["api_key"], doc["id"])
    assert final["status"] == "ready", final["error"]


async def test_upload_docx(client):
    docx = DocxDocument()
    docx.add_heading("Refunds", level=1)
    docx.add_paragraph("Refunds within 30 days.")
    buf = io.BytesIO()
    docx.save(buf)
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.docx", buf.getvalue())
    final = await get_document(client, company["api_key"], doc["id"])
    assert final["status"] == "ready", final["error"]


async def test_duplicate_content_skipped(client):
    company = await create_company(client)
    first = await upload(client, company["api_key"], "policy.txt", POLICY.encode())
    again = await upload(client, company["api_key"], "copy.txt", POLICY.encode())
    assert again["duplicate_of"] == first["id"]
    response = await client.get("/api/v1/documents", headers=auth(company["api_key"]))
    assert len(response.json()) == 1


async def test_same_content_different_companies_both_kept(client):
    acme = await create_company(client, "Acme")
    other = await create_company(client, "Other")
    await upload(client, acme["api_key"], "policy.txt", POLICY.encode())
    doc = await upload(client, other["api_key"], "policy.txt", POLICY.encode())
    assert doc["duplicate_of"] is None


async def test_unsupported_type_415(client):
    company = await create_company(client)
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("tool.exe", b"MZ")},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 415


async def test_empty_file_422(client):
    company = await create_company(client)
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("empty.txt", b"")},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 422


async def test_oversized_file_413(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    company = await create_company(client)
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("big.txt", b"x" * (2 * 1024 * 1024))},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 413
    assert "MAX_UPLOAD_MB" in response.json()["detail"]


async def test_unreadable_pdf_marks_failed_with_message(client):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "broken.pdf", b"%PDF-1.4 garbage")
    final = await get_document(client, company["api_key"], doc["id"])
    assert final["status"] == "failed"
    assert "Unreadable PDF" in final["error"]


async def test_delete_document(client):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.txt", POLICY.encode())
    response = await client.delete(
        f"/api/v1/documents/{doc['id']}", headers=auth(company["api_key"])
    )
    assert response.status_code == 204
    listing = await client.get("/api/v1/documents", headers=auth(company["api_key"]))
    assert listing.json() == []


async def test_reindex_document(client):
    company = await create_company(client)
    doc = await upload(client, company["api_key"], "policy.txt", POLICY.encode())
    response = await client.post(
        f"/api/v1/documents/{doc['id']}/reindex", headers=auth(company["api_key"])
    )
    assert response.status_code == 202
    final = await get_document(client, company["api_key"], doc["id"])
    assert final["status"] == "ready", final["error"]
    assert final["chunk_count"] >= 1


async def test_company_isolation(client):
    acme = await create_company(client, "Acme")
    other = await create_company(client, "Other")
    doc = await upload(client, acme["api_key"], "secret.txt", b"Acme confidential policy")

    listing = await client.get("/api/v1/documents", headers=auth(other["api_key"]))
    assert listing.json() == []

    response = await client.delete(
        f"/api/v1/documents/{doc['id']}", headers=auth(other["api_key"])
    )
    assert response.status_code == 404

    response = await client.post(
        f"/api/v1/documents/{doc['id']}/reindex", headers=auth(other["api_key"])
    )
    assert response.status_code == 404

    search = await client.post(
        "/api/v1/search", json={"query": "confidential"}, headers=auth(other["api_key"])
    )
    assert search.status_code == 200
    assert search.json()["hits"] == []