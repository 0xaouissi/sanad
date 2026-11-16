"""API-key hashing and generation."""

from app.core.security import generate_api_key, hash_api_key, keys_match


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