"""Dashboard sessions: random tokens in the KV store, referenced by an httpOnly cookie.

Each session carries its own CSRF token; mutating endpoints require it in
X-CSRF-Token. Sessions fail closed: an unreachable backend is a 503, never
an anonymous pass.
"""

import json
import secrets
from dataclasses import dataclass
from uuid import UUID

from fastapi import Response

from app.core.config import Settings
from app.providers.kv.base import KVStore

COOKIE_NAME = "sanad_session"


@dataclass
class SessionData:
    user_id: UUID
    company_id: UUID
    csrf: str


async def create_session(
    kv: KVStore, user_id: UUID, company_id: UUID, settings: Settings
) -> tuple[str, SessionData]:
    token = secrets.token_urlsafe(32)
    data = SessionData(user_id=user_id, company_id=company_id, csrf=secrets.token_urlsafe(32))
    payload = json.dumps(
        {"user_id": str(user_id), "company_id": str(company_id), "csrf": data.csrf}
    )
    await kv.set(
        f"sess:{token}", payload, ttl_seconds=settings.dashboard_session_hours * 3600
    )
    return token, data


async def get_session(kv: KVStore, token: str) -> SessionData | None:
    raw = await kv.get(f"sess:{token}")
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
        return SessionData(
            user_id=UUID(payload["user_id"]),
            company_id=UUID(payload["company_id"]),
            csrf=payload["csrf"],
        )
    except (ValueError, KeyError, TypeError):
        return None


async def delete_session(kv: KVStore, token: str) -> None:
    await kv.delete_prefix(f"sess:{token}")


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.dashboard_session_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure
    )