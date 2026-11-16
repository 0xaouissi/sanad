from app.core.passwords import hash_password, verify_password


def test_roundtrip() -> None:
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored)


def test_wrong_password_fails() -> None:
    stored = hash_password("s3cret-password")
    assert not verify_password("s3cret-passworD", stored)
    assert not verify_password("", stored)


def test_hashes_are_salted() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_unicode_password_roundtrip() -> None:
    stored = hash_password("كلمة-السر-١٢٣")
    assert verify_password("كلمة-السر-١٢٣", stored)


def test_tampered_hash_fails() -> None:
    stored = hash_password("s3cret-password")
    algo, n, r, p, salt, digest = stored.split("$")
    flipped = "0" if digest[0] != "0" else "1"
    tampered = f"{algo}${n}${r}${p}${salt}${flipped}{digest[1:]}"
    assert not verify_password("s3cret-password", tampered)


def test_malformed_stored_values_fail_closed() -> None:
    malformed = [
        "",
        "plaintext",
        "bcrypt$1$2$3$aa$bb",
        "scrypt$abc$8$1$zz$00",
        "scrypt$16384$8$1$$",
    ]
    for stored in malformed:
        assert not verify_password("anything", stored)