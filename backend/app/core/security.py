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