"""Bot check through the real chat endpoint on the public site-key path."""

import time

import pytest

from app.core.config import get_settings
from tests.integration.conftest import auth, create_company


@pytest.fixture
async def site_company(client, monkeypatch):
    monkeypatch.setenv("BOT_CHECK_ENABLED", "true")
    get_settings.cache_clear()
    company = await create_company(client)
    response = await client.put(
        "/api/v1/companies/domains",
        json={"domains": ["acme.com"]},
        headers=auth(company["api_key"]),
    )
    assert response.status_code == 200
    return company


def site_headers(company, origin="https://acme.com"):
    return {"X-Site-Key": company["site_key"], "Origin": origin}


async def _chat(client, company, **payload):
    return await client.post(
        "/api/v1/chat",
        json={"message": "What is the refund policy?", **payload},
        headers=site_headers(company),
    )


async def test_honeypot_filled_is_rejected(client, site_company):
    response = await _chat(
        client, site_company, website="http://spam.example",
        opened_at=(time.time() - 10) * 1000,
    )
    assert response.status_code == 400
    assert "website" in response.json()["detail"]


async def test_missing_opened_at_is_rejected(client, site_company):
    response = await _chat(client, site_company)
    assert response.status_code == 400
    assert "opened_at" in response.json()["detail"]


async def test_sending_too_fast_is_rejected(client, site_company):
    response = await _chat(client, site_company, opened_at=time.time() * 1000)
    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1


async def test_patient_visitor_passes(client, site_company):
    response = await _chat(client, site_company, opened_at=(time.time() - 5) * 1000)
    assert response.status_code == 200, response.text


async def test_secret_key_path_is_exempt(client, site_company):
    response = await client.post(
        "/api/v1/chat",
        json={"message": "What is the refund policy?"},
        headers=auth(site_company["api_key"]),
    )
    assert response.status_code == 200, response.text


async def test_disabled_check_accepts_plain_requests(client, site_company, monkeypatch):
    monkeypatch.setenv("BOT_CHECK_ENABLED", "false")
    get_settings.cache_clear()
    response = await _chat(client, site_company)
    assert response.status_code == 200, response.text