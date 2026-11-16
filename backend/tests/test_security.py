"""API-key hashing, generation, and site-key domain matching."""

import pytest

from app.core.security import (
    domain_allowed,
    generate_api_key,
    generate_site_key,
    hash_api_key,
    keys_match,
    normalize_domains,
    origin_host,
)


def test_hash_is_sha256_hex():
    digest = hash_api_key("sk-test")
    assert len(digest) == 64
    assert digest == hash_api_key("sk-test")
    assert digest != hash_api_key("sk-other")


def test_generated_keys_unique_and_prefixed():
    keys = {generate_api_key() for _ in range(50)}
    assert len(keys) == 50
    assert all(k.startswith("sk-") and len(k) > 30 for k in keys)


def test_keys_match():
    assert keys_match("secret", "secret")
    assert not keys_match("secret", "Secret")
    assert not keys_match("", "secret")


def test_site_keys_unique_and_public_prefixed():
    keys = {generate_site_key() for _ in range(50)}
    assert len(keys) == 50
    assert all(k.startswith("pk-") and len(k) > 20 for k in keys)


@pytest.mark.parametrize(
    ("origin", "host"),
    [
        ("https://example.com", "example.com"),
        ("https://Example.COM:8443", "example.com"),
        ("http://localhost:5500", "localhost"),
        ("https://sub.example.com", "sub.example.com"),
        (None, None),
        ("", None),
        ("null", None),
    ],
)
def test_origin_host(origin: str | None, host: str | None):
    assert origin_host(origin) == host


def test_normalize_domains_lowercases_and_dedupes():
    assert normalize_domains([" Example.com ", "*.Example.com", "example.com"]) == [
        "example.com",
        "*.example.com",
    ]


def test_normalize_domains_allows_localhost_for_dev():
    assert normalize_domains(["localhost"]) == ["localhost"]


@pytest.mark.parametrize(
    "bad",
    [
        "https://example.com",
        "example.com/path",
        "example.com:8080",
        "",
        "   ",
        "exa mple.com",
        "-bad.com",
        "example..com",
    ],
)
def test_normalize_domains_rejects_invalid(bad: str):
    with pytest.raises(ValueError, match="Invalid domain"):
        normalize_domains([bad])


@pytest.mark.parametrize(
    ("host", "domains", "expected"),
    [
        ("example.com", ["example.com"], True),
        ("EXAMPLE.COM", ["example.com"], True),
        ("shop.example.com", ["*.example.com"], True),
        ("deep.shop.example.com", ["*.example.com"], True),
        ("example.com", ["*.example.com"], False),
        ("notexample.com", ["example.com"], False),
        ("evil-example.com", ["*.example.com"], False),
        ("example.com.evil.net", ["example.com"], False),
        ("other.com", ["example.com"], False),
        ("example.com", [], False),
    ],
)
def test_domain_allowed(host: str, domains: list[str], expected: bool):
    assert domain_allowed(host, domains) is expected