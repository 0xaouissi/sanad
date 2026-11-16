"""Public site key: Origin allowlist matrix, domains endpoint, secret-key parity.

Real PostgreSQL, fake embeddings and scripted LLM. The widget path (X-Site-Key)
must only work from allowed domains; the secret path (X-API-Key) is unchanged.
"""

import json

from httpx import AsyncClient

from tests.integration.conftest import ScriptedLLM, auth, create_company, upload

POLICY = """# Refund policy
Customers may request a full refund within 30 days of purchase.
"""

QUESTION = "What is the refund policy?"


def site_auth(site_key: str, origin: str | None = None) -> dict[str, str]:
    headers = {"X-Site-Key": site_key}
    if origin is not None:
        headers["Origin"] = origin
    return headers


async def _company_with_domains(
    client: AsyncClient, domains: list[str], name: str = "Acme"
) -> dict:
    company = await create_company(client, name)
    response = await client.put(
        "/api/v1/companies/domains",
        json={"domains": domains},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["domains"] == domains
    return company


async def _upload_policy(client: AsyncClient, company: dict) -> None:
    await upload(client, company["api_key"], "policy.md", POLICY.encode())


async def test_create_company_returns_public_site_key(client: AsyncClient) -> None:
    company = await create_company(client)
    assert company["site_key"].startswith("pk-")
    assert company["site_key"] != company["api_key"]


async def test_chat_with_site_key_from_allowed_origin(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_domains(client, ["acme.com"])
    await _upload_policy(client, company)
    fake_llm.answers = ["You can request a refund within 30 days [1]."]
    response = await client.post(
        "/api/v1/chat",
        json={"message": QUESTION},
        headers=site_auth(company["site_key"], "https://acme.com"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["citations"][0]["filename"] == "policy.md"


async def test_site_key_host_match_is_case_insensitive(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_domains(client, ["acme.com"])
    await _upload_policy(client, company)
    response = await client.post(
        "/api/v1/chat",
        json={"message": QUESTION},
        headers=site_auth(company["site_key"], "https://ACME.Com:443"),
    )
    assert response.status_code == 200, response.text


async def test_wildcard_covers_subdomains_not_apex(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_domains(client, ["*.acme.com"])
    await _upload_policy(client, company)
    headers = site_auth(company["site_key"], "https://shop.acme.com")
    response = await client.post("/api/v1/chat", json={"message": QUESTION}, headers=headers)
    assert response.status_code == 200, response.text
    apex = await client.post(
        "/api/v1/chat",
        json={"message": QUESTION},
        headers=site_auth(company["site_key"], "https://acme.com"),
    )
    assert apex.status_code == 403


async def test_site_key_from_other_origin_is_403_with_hint(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_domains(client, ["acme.com"])
    response = await client.post(
        "/api/v1/chat",
        json={"message": QUESTION},
        headers=site_auth(company["site_key"], "https://evil.com"),
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "evil.com" in detail
    assert "PUT /api/v1/companies/domains" in detail
    assert fake_llm.calls == []


async def test_site_key_without_origin_is_403(client: AsyncClient) -> None:
    company = await _company_with_domains(client, ["acme.com"])
    response = await client.post(
        "/api/v1/chat", json={"message": QUESTION}, headers=site_auth(company["site_key"])
    )
    assert response.status_code == 403
    assert "Origin" in response.json()["detail"]


async def test_site_key_with_no_domains_configured_is_403(client: AsyncClient) -> None:
    company = await create_company(client)
    response = await client.post(
        "/api/v1/chat",
        json={"message": QUESTION},
        headers=site_auth(company["site_key"], "https://acme.com"),
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert "no allowed domains" in detail
    assert "PUT /api/v1/companies/domains" in detail


async def test_invalid_site_key_is_401(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/chat",
        json={"message": QUESTION},
        headers=site_auth("pk-does-not-exist", "https://acme.com"),
    )
    assert response.status_code == 401


async def test_secret_key_still_works_without_origin(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_domains(client, ["acme.com"])
    await _upload_policy(client, company)
    response = await client.post(
        "/api/v1/chat", json={"message": QUESTION}, headers=auth(company["api_key"])
    )
    assert response.status_code == 200, response.text


async def test_site_key_cannot_manage_documents_or_domains(client: AsyncClient) -> None:
    company = await _company_with_domains(client, ["acme.com"])
    headers = site_auth(company["site_key"], "https://acme.com")
    listing = await client.get("/api/v1/documents", headers=headers)
    assert listing.status_code == 401
    upload_response = await client.post(
        "/api/v1/documents", files={"file": ("x.md", b"# Hi")}, headers=headers
    )
    assert upload_response.status_code == 401
    domains = await client.put(
        "/api/v1/companies/domains", json={"domains": ["evil.com"]}, headers=headers
    )
    assert domains.status_code == 401
    search = await client.post(
        "/api/v1/search", json={"query": "refund"}, headers=headers
    )
    assert search.status_code == 401


async def test_domains_endpoint_validates_entries(client: AsyncClient) -> None:
    company = await create_company(client)
    response = await client.put(
        "/api/v1/companies/domains",
        json={"domains": ["https://acme.com"]},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 422
    assert "Invalid domain" in response.json()["detail"]


async def test_domains_update_takes_effect_immediately(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_domains(client, ["old.com"])
    await _upload_policy(client, company)
    headers = auth(company["api_key"])
    old = await client.post(
        "/api/v1/chat",
        json={"message": QUESTION},
        headers=site_auth(company["site_key"], "https://old.com"),
    )
    assert old.status_code == 200
    update = await client.put(
        "/api/v1/companies/domains", json={"domains": ["new.com"]}, headers=headers
    )
    assert update.status_code == 200
    denied = await client.post(
        "/api/v1/chat",
        json={"message": QUESTION},
        headers=site_auth(company["site_key"], "https://old.com"),
    )
    assert denied.status_code == 403
    allowed = await client.post(
        "/api/v1/chat",
        json={"message": QUESTION},
        headers=site_auth(company["site_key"], "https://new.com"),
    )
    assert allowed.status_code == 200


async def test_site_key_streaming_from_allowed_origin(
    client: AsyncClient, fake_llm: ScriptedLLM
) -> None:
    company = await _company_with_domains(client, ["acme.com"])
    await _upload_policy(client, company)
    fake_llm.answers = ["Refunds are possible within 30 days [1]."]
    response = await client.post(
        "/api/v1/chat",
        json={"message": QUESTION, "stream": True},
        headers=site_auth(company["site_key"], "https://acme.com"),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "done"
    assert events[-1]["citations"][0]["filename"] == "policy.md"


async def test_cors_preflight_allows_widget_headers(client: AsyncClient) -> None:
    response = await client.options(
        "/api/v1/chat",
        headers={
            "Origin": "https://acme.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-site-key",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "x-site-key" in response.headers["access-control-allow-headers"].lower()