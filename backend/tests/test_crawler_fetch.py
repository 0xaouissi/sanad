"""Fetcher guards with httpx.MockTransport: IP pinning, redirect re-validation,
size/type caps, robots handling and BFS limits. No DB, no live network."""

import ipaddress
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.core.config import Settings
from app.db.models import CrawlSource, CrawlStatus
from app.rag.crawl import CrawlError
from app.services.crawler import (
    _crawl_pages,
    check_source_url,
    crawl_in_progress,
    safe_fetch,
)


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Public hosts resolve to a fixed public IP; IP literals resolve to themselves."""

    def fake_resolve(host):
        if host == "internal.example.com":
            return ["127.0.0.1"]
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return ["93.184.216.34"]
        return [host]

    monkeypatch.setattr("app.rag.crawl.resolve_host", fake_resolve)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False, follow_redirects=False
    )


def _deadline(seconds: float = 60.0) -> float:
    return time.monotonic() + seconds


async def test_fetch_pins_ip_and_keeps_original_host():
    seen = {}

    def handler(request):
        seen["url_host"] = request.url.host
        seen["host_header"] = request.headers["host"]
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<p>Hi</p>")

    async with _client(handler) as client:
        url, ctype, text = await safe_fetch(
            "https://example.com/page", Settings(), client, "example.com", _deadline()
        )
    assert (url, ctype, text) == ("https://example.com/page", "text/html", "<p>Hi</p>")
    assert seen["url_host"] == "93.184.216.34"
    assert seen["host_header"] == "example.com"
    assert seen["sni"] == "example.com"


async def test_fetch_http_port_preserved():
    seen = {}

    def handler(request):
        seen["port"] = request.url.port
        seen["host_header"] = request.headers["host"]
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="ok")

    async with _client(handler) as client:
        await safe_fetch(
            "http://example.com:8080/x", Settings(), client, "example.com", _deadline()
        )
    assert seen["port"] == 8080
    assert seen["host_header"] == "example.com:8080"
    assert seen["sni"] is None


async def test_redirect_to_private_ip_is_blocked():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://internal.example.com/"})

    async with _client(handler) as client:
        with pytest.raises(CrawlError, match="SSRF"):
            await safe_fetch(
                "https://example.com/", Settings(), client, "example.com", _deadline()
            )
    assert len(calls) == 1  # the redirect target was never connected to


async def test_redirect_to_raw_private_ip_is_blocked():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    async with _client(handler) as client:
        with pytest.raises(CrawlError):
            await safe_fetch(
                "https://example.com/", Settings(), client, "example.com", _deadline()
            )


async def test_redirect_off_domain_is_blocked():
    def handler(request):
        return httpx.Response(302, headers={"location": "https://evil.com/x"})

    async with _client(handler) as client:
        with pytest.raises(CrawlError, match="outside"):
            await safe_fetch(
                "https://example.com/", Settings(), client, "example.com", _deadline()
            )


async def test_relative_redirect_is_followed_and_revalidated():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<p>new</p>")

    async with _client(handler) as client:
        url, _, text = await safe_fetch(
            "https://example.com/old", Settings(), client, "example.com", _deadline()
        )
    assert url == "https://example.com/new"
    assert text == "<p>new</p>"


async def test_redirect_chain_is_capped():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(302, headers={"location": f"/loop{len(calls)}"})

    async with _client(handler) as client:
        with pytest.raises(CrawlError, match="Too many redirects"):
            await safe_fetch(
                "https://example.com/", Settings(), client, "example.com", _deadline()
            )
    assert len(calls) == 6  # initial request + 5 redirects


async def test_redirect_to_non_http_scheme_is_blocked():
    def handler(request):
        return httpx.Response(302, headers={"location": "ftp://example.com/file"})

    async with _client(handler) as client:
        with pytest.raises(CrawlError, match="non-http"):
            await safe_fetch(
                "https://example.com/", Settings(), client, "example.com", _deadline()
            )


async def test_oversize_page_is_rejected():
    def handler(request):
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=b"x" * 2000
        )

    async with _client(handler) as client:
        with pytest.raises(CrawlError, match="larger than"):
            await safe_fetch(
                "https://example.com/",
                Settings(crawl_max_page_bytes=1024),
                client,
                "example.com",
                _deadline(),
            )


async def test_unsupported_content_type_is_rejected():
    def handler(request):
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

    async with _client(handler) as client:
        with pytest.raises(CrawlError, match="content type"):
            await safe_fetch(
                "https://example.com/", Settings(), client, "example.com", _deadline()
            )


@pytest.mark.parametrize("status", [404, 500])
async def test_http_error_status_is_reported(status):
    def handler(request):
        return httpx.Response(status)

    async with _client(handler) as client:
        with pytest.raises(CrawlError) as excinfo:
            await safe_fetch(
                "https://example.com/", Settings(), client, "example.com", _deadline()
            )
    assert excinfo.value.status_code == status


async def test_expired_time_budget_refuses_before_connecting():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, text="x")

    async with _client(handler) as client:
        with pytest.raises(CrawlError, match="time budget"):
            await safe_fetch(
                "https://example.com/",
                Settings(),
                client,
                "example.com",
                time.monotonic() - 1,
            )
    assert not calls


async def test_network_error_is_wrapped_with_fix_hint():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    async with _client(handler) as client:
        with pytest.raises(CrawlError, match="Could not fetch"):
            await safe_fetch(
                "https://example.com/", Settings(), client, "example.com", _deadline()
            )


async def test_charset_from_content_type_is_used():
    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=iso-8859-1"},
            content="café".encode("iso-8859-1"),
        )

    async with _client(handler) as client:
        _, _, text = await safe_fetch(
            "https://example.com/", Settings(), client, "example.com", _deadline()
        )
    assert "café" in text


def test_check_source_url_canonicalizes_and_validates():
    assert check_source_url("HTTPS://Example.com/policies#x", Settings()) == (
        "https://example.com/policies"
    )
    with pytest.raises(CrawlError, match="SSRF"):
        check_source_url("http://127.0.0.1:8000/", Settings())
    assert check_source_url(
        "http://127.0.0.1:8000/", Settings(crawl_allow_private=True)
    ) == "http://127.0.0.1:8000/"


def test_crawl_in_progress_fresh_vs_stale():
    now = datetime.now(UTC)
    fresh = CrawlSource(status=CrawlStatus.CRAWLING, updated_at=now)
    stale = CrawlSource(status=CrawlStatus.CRAWLING, updated_at=now - timedelta(minutes=31))
    ready = CrawlSource(status=CrawlStatus.READY, updated_at=now)
    assert crawl_in_progress(fresh)
    assert not crawl_in_progress(stale)
    assert not crawl_in_progress(ready)


@pytest.fixture
def mock_site(monkeypatch):
    """Route _crawl_pages' internal AsyncClient through a MockTransport."""

    def install(handler):
        real_client = httpx.AsyncClient
        monkeypatch.setattr(
            "app.services.crawler.httpx.AsyncClient",
            lambda **kwargs: real_client(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        )

    return install


def _site_handler(pages: dict, robots: str | None = "User-agent: *\nDisallow: /private\n"):
    requested = []

    def handler(request):
        path = request.url.path
        requested.append(path)
        if path == "/robots.txt":
            if robots is None:
                return httpx.Response(500)
            if robots == "404":
                return httpx.Response(404)
            return httpx.Response(200, headers={"content-type": "text/plain"}, text=robots)
        if path in pages:
            body = pages[path]
            if isinstance(body, tuple):
                return httpx.Response(200, headers={"content-type": body[0]}, text=body[1])
            return httpx.Response(200, headers={"content-type": "text/html"}, text=body)
        return httpx.Response(404)

    return handler, requested


async def test_crawl_bfs_respects_robots_and_domain(mock_site):
    pages = {
        "/": '<a href="/about">a</a><a href="/private/secret">p</a>'
        '<a href="https://evil.com/x">e</a><a href="/about#frag">dup</a>',
        "/about": '<a href="/">home</a><a href="/contact">c</a>',
        "/contact": "<p>Contact us</p>",
        "/private/secret": "<p>secret</p>",
    }
    handler, requested = _site_handler(pages)
    mock_site(handler)
    crawled = await _crawl_pages("https://example.com/", Settings())
    assert {p.url for p in crawled} == {
        "https://example.com/",
        "https://example.com/about",
        "https://example.com/contact",
    }
    assert "/private/secret" not in requested
    assert requested.count("/about") == 1


async def test_crawl_page_cap(mock_site):
    pages = {"/": '<a href="/a">a</a><a href="/b">b</a><a href="/c">c</a>'}
    pages.update({f"/{x}": f"<p>{x}</p>" for x in "abc"})
    handler, _ = _site_handler(pages)
    mock_site(handler)
    crawled = await _crawl_pages("https://example.com/", Settings(crawl_max_pages=2))
    assert len(crawled) == 2


async def test_crawl_seed_disallowed_by_robots(mock_site):
    handler, _ = _site_handler({"/": "<p>hi</p>"}, robots="User-agent: *\nDisallow: /\n")
    mock_site(handler)
    with pytest.raises(CrawlError, match="disallows"):
        await _crawl_pages("https://example.com/", Settings())


async def test_crawl_robots_404_allows_all(mock_site):
    handler, _ = _site_handler({"/": "<p>hi</p>"}, robots="404")
    mock_site(handler)
    crawled = await _crawl_pages("https://example.com/", Settings())
    assert len(crawled) == 1
    assert crawled[0].text == "hi"


async def test_crawl_unreachable_robots_fails_conservatively(mock_site):
    handler, _ = _site_handler({"/": "<p>hi</p>"}, robots=None)
    mock_site(handler)
    with pytest.raises(CrawlError, match="robots.txt"):
        await _crawl_pages("https://example.com/", Settings())


async def test_crawl_seed_failure_raises(mock_site):
    handler, _ = _site_handler({}, robots="404")
    mock_site(handler)
    with pytest.raises(CrawlError, match="HTTP 404"):
        await _crawl_pages("https://example.com/", Settings())


async def test_crawl_skips_broken_links(mock_site):
    pages = {"/": '<a href="/missing">m</a><a href="/ok">o</a>', "/ok": "<p>ok</p>"}
    handler, _ = _site_handler(pages)
    mock_site(handler)
    crawled = await _crawl_pages("https://example.com/", Settings())
    assert {p.url for p in crawled} == {"https://example.com/", "https://example.com/ok"}


async def test_crawl_plain_text_page(mock_site):
    pages = {"/": ("text/plain", "Refunds within 30 days.")}
    handler, _ = _site_handler(pages)
    mock_site(handler)
    crawled = await _crawl_pages("https://example.com/", Settings())
    assert crawled[0].title == ""
    assert crawled[0].text == "Refunds within 30 days."