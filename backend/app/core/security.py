import hashlib
import hmac
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return f"sk-{secrets.token_urlsafe(32)}"


def keys_match(provided: str, expected: str) -> bool:
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


async def company_for_api_key(session: AsyncSession, api_key: str) -> Company | None:
    return await session.scalar(
        select(Company).where(Company.api_key_hash == hash_api_key(api_key))
    )