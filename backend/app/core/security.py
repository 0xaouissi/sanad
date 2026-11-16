import hashlib
import hmac
import re
import secrets
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return f"sk-{secrets.token_urlsafe(32)}"


def generate_site_key() -> str:
    return f"pk-{secrets.token_urlsafe(24)}"


def keys_match(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


async def company_for_api_key(session: AsyncSession, api_key: str) -> Company | None:
    return await session.scalar(
        select(Company).where(Company.api_key_hash == hash_api_key(api_key))
    )


async def company_for_site_key(session: AsyncSession, site_key: str) -> Company | None:
    return await session.scalar(select(Company).where(Company.site_key == site_key))


def origin_host(origin: str | None) -> str | None:
    if not origin:
        return None
    try:
        return urlsplit(origin).hostname
    except ValueError:
        return None


# Bare hostnames ("example.com", "localhost") or one wildcard level ("*.example.com").
_DOMAIN_RE = re.compile(
    r"(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*"
)


def normalize_domains(domains: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in domains:
        entry = raw.strip().lower()
        if not _DOMAIN_RE.fullmatch(entry):
            raise ValueError(
                f"Invalid domain {raw!r}. Use a hostname like 'example.com' or "
                "'*.example.com' — no scheme, port or path."
            )
        if entry not in normalized:
            normalized.append(entry)
    return normalized


def domain_allowed(host: str, domains: list[str]) -> bool:
    host = host.lower()
    for entry in domains:
        if entry.startswith("*."):
            # Wildcard covers subdomains only; list the apex separately if needed.
            if host.endswith("." + entry[2:]):
                return True
        elif host == entry:
            return True
    return False


# Header-injection guard: CR/LF/NUL and other control characters never belong
# in an email address or a Telegram chat id, and would let a visitor smuggle
# extra SMTP headers (Bcc:) or break the Telegram payload.
def _has_control_chars(value: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7F or c in "\u2028\u2029" for c in value)


def clean_header_text(text: str) -> str:
    return "".join(c for c in text if not _has_control_chars(c))


# ASCII only: stdlib smtplib does not negotiate SMTPUTF8, so internationalized
# addresses would bounce. Requires a dot in the domain (no "user@localhost").
_HANDOFF_EMAIL_RE = re.compile(
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+"
)


def validate_handoff_email(email: str) -> str:
    if _has_control_chars(email):
        raise ValueError(
            "email must not contain line breaks or control characters "
            "(header-injection protection)"
        )
    value = email.strip()
    if len(value) > 320 or len(value.split("@")[0]) > 64:
        raise ValueError("email is too long: max 320 characters, 64 before the @")
    if not _HANDOFF_EMAIL_RE.fullmatch(value):
        raise ValueError("email must be a valid address like name@example.com")
    return value


_CHAT_ID_RE = re.compile(r"-?\d{1,20}|@[A-Za-z0-9_]{5,32}")


def validate_chat_id(chat_id: str) -> str:
    if _has_control_chars(chat_id):
        raise ValueError(
            "telegram_chat_id must not contain line breaks or control characters"
        )
    value = chat_id.strip()
    if not _CHAT_ID_RE.fullmatch(value):
        raise ValueError(
            "telegram_chat_id must be a numeric chat id (e.g. 123456789 or "
            "-1001234567890 for a group) or @channelusername"
        )
    return value