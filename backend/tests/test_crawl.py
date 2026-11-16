"""Crawler core: SSRF IP/URL guards, domain checks, link normalization,
HTML extraction and robots.txt parsing — all pure, no live network."""

import socket

import pytest

from app.core.config import Settings
from app.rag.crawl import (
    CrawlError,
    canonical_url,
    extract_page,
    is_blocked_ip,
    normalize_link,
    parse_robots,
    resolve_and_validate,
    resolve_host,
    same_domain,
    validate_url,
)

BLOCKED_IPS = [
    "127.0.0.1",
    "127.8.8.8",
    "10.0.0.5",
    "172.16.0.1",
    "192.168.1.1",
    "169.254.169.254",  # cloud metadata endpoint
    "0.0.0.0",
    "100.64.0.1",  # CGNAT
    "100.127.255.254",
    "224.0.0.1",
    "240.0.0.1",
    "192.0.2.1",  # TEST-NET, not globally routable
    "::1",
    "fe80::1",
    "fe80::1%eth0",
    "fc00::1",
    "fd12:3456::1",
    "::",
    "ff02::1",
    "::ffff:127.0.0.1",  # IPv4-mapped loopback
    "::ffff:169.254.169.254",
    "2001:db8::1",  # documentation range
    "not-an-ip",
]

PUBLIC_IPS = [
    "93.184.216.34",
    "8.8.8.8",
    "1.1.1.1",
    "100.128.0.1",  # just outside CGNAT
    "2606:4700:4700::1111",
    "2001:4860:4860::8888",
    "::ffff:93.184.216.34",
]


@pytest.mark.parametrize("ip", BLOCKED_IPS)
def test_private_and_local_ips_are_blocked(ip):
    assert is_blocked_ip(ip)


@pytest.mark.parametrize("ip", PUBLIC_IPS)
def test_public_ips_are_allowed(ip):
    assert not is_blocked_ip(ip)


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,hi",
        "gopher://example.com/",
        "example.com/policies",
        "http:///no-host",
        "http://user:pass@example.com/",
        "http://example.com:99999/",
        "",
    ],
)
def test_invalid_or_unsafe_urls_are_rejected(url):
    with pytest.raises(CrawlError):
        validate_url(url)


def test_valid_urls_pass_and_canonicalize():
    assert validate_url("https://example.com/policies?q=1").hostname == "example.com"
    assert validate_url("http://example.com:8080/x").port == 8080
    assert canonical_url("HTTPS://Example.COM") == "https://example.com/"
    assert canonical_url("https://example.com/a#frag") == "https://example.com/a"
    assert canonical_url("http://example.com:8080") == "http://example.com:8080/"


def test_resolve_host_dedupes_sorts_and_strips_zones(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        return [
            (socket.AF_INET, type, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, type, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET6, type, 6, "", ("fe80::1%eth0", 0, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert resolve_host("example.com") == ["93.184.216.34", "fe80::1"]


def test_resolve_host_dns_failure_is_actionable(monkeypatch):
    def fake_getaddrinfo(host, port, type=None):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(CrawlError, match="Could not resolve"):
        resolve_host("nonexistent.invalid")


def test_resolve_and_validate_blocks_if_any_answer_is_private(monkeypatch):
    monkeypatch.setattr(
        "app.rag.crawl.resolve_host", lambda host: ["93.184.216.34", "127.0.0.1"]
    )
    with pytest.raises(CrawlError, match="SSRF"):
        resolve_and_validate("evil.example.com", Settings())


def test_resolve_and_validate_allows_public(monkeypatch):
    monkeypatch.setattr("app.rag.crawl.resolve_host", lambda host: ["93.184.216.34"])
    assert resolve_and_validate("example.com", Settings()) == ["93.184.216.34"]


def test_resolve_and_validate_dev_override(monkeypatch):
    monkeypatch.setattr("app.rag.crawl.resolve_host", lambda host: ["127.0.0.1"])
    settings = Settings(crawl_allow_private=True)
    assert resolve_and_validate("localhost", settings) == ["127.0.0.1"]


def test_resolve_and_validate_empty_answer(monkeypatch):
    monkeypatch.setattr("app.rag.crawl.resolve_host", lambda host: [])
    with pytest.raises(CrawlError, match="no addresses"):
        resolve_and_validate("example.com", Settings())


@pytest.mark.parametrize(
    ("root", "host", "expected"),
    [
        ("example.com", "example.com", True),
        ("example.com", "www.example.com", True),
        ("www.example.com", "example.com", True),
        ("example.com", "docs.example.com", True),
        ("docs.example.com", "example.com", True),
        ("EXAMPLE.COM", "Docs.Example.Com", True),
        ("example.com", "notexample.com", False),
        ("example.com", "example.com.evil.com", False),
        ("example.com", "evil.com", False),
        ("localhost", "127.0.0.1", False),
        ("", "example.com", False),
    ],
)
def test_same_domain(root, host, expected):
    assert same_domain(root, host) is expected


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("/about", "https://example.com/about"),
        ("team.html", "https://example.com/policies/team.html"),
        ("../x", "https://example.com/x"),
        ("https://example.com/a#frag", "https://example.com/a"),
        ("//cdn.example.com/x", "https://cdn.example.com/x"),
        ("HTTPS://Example.COM/Path", "https://example.com/Path"),
        ("#section", None),
        ("", None),
        ("   ", None),
        ("mailto:x@y.z", None),
        ("tel:+123456789", None),
        ("javascript:alert(1)", None),
        ("data:text/html,hi", None),
        ("ftp://example.com/f", None),
        ("http://user:pass@example.com/", None),
        ("http://example.com:99999/", None),
    ],
)
def test_normalize_link(href, expected):
    assert normalize_link("https://example.com/policies/", href) == expected


def test_extract_page_text_title_and_links():
    html = """<html><head><title>Policy &amp; Rules</title>
    <style>body{color:red}</style></head>
    <body><script>var a = 1; if (a < 2) { alert('x'); }</script>
    <h1>Refunds</h1><p>You have <b>30 days</b> to ask.</p>
    <ul><li>Keep the receipt</li><li>Original packaging</li></ul>
    <a href="/shipping">Shipping</a><a href="mailto:x@y.z">Mail</a>
    <noscript>Enable JS</noscript><template>hidden</template>
    </body></html>"""
    page = extract_page(html)
    assert page.title == "Policy & Rules"
    assert "# Refunds" in page.text
    assert "You have 30 days to ask." in page.text
    assert "- Keep the receipt" in page.text
    assert "- Original packaging" in page.text
    assert "color:red" not in page.text
    assert "alert" not in page.text
    assert "Enable JS" not in page.text
    assert "hidden" not in page.text
    assert page.links == ["/shipping", "mailto:x@y.z"]


def test_extract_page_arabic_and_whitespace():
    html = (
        "<h1>سياسة الاسترجاع</h1><p>يمكنك   طلب استرجاع المبلغ خلال 30 يومًا.</p>"
        "<p>line one<br>line two</p>"
    )
    page = extract_page(html)
    assert "# سياسة الاسترجاع" in page.text
    assert "يمكنك طلب استرجاع المبلغ خلال 30 يومًا." in page.text
    assert "line one\nline two" in page.text


def test_extract_page_empty():
    page = extract_page("")
    assert page.title == ""
    assert page.text == ""
    assert page.links == []


def test_robots_empty_allows_everything():
    robots = parse_robots("", "https://example.com/robots.txt")
    assert robots.can_fetch("SanadBot/0.1", "https://example.com/anything")


def test_robots_disallow_rules():
    text = "User-agent: *\nDisallow: /private\n\nUser-agent: SanadBot\nDisallow: /secret\n"
    robots = parse_robots(text, "https://example.com/robots.txt")
    assert not robots.can_fetch("OtherBot", "https://example.com/private/x")
    assert robots.can_fetch("OtherBot", "https://example.com/public")
    assert not robots.can_fetch("SanadBot/0.1 (self-hosted)", "https://example.com/secret/x")
    assert robots.can_fetch("SanadBot/0.1 (self-hosted)", "https://example.com/public")