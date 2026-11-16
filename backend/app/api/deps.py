from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    company_for_api_key,
    company_for_site_key,
    domain_allowed,
    keys_match,
    origin_host,
)
from app.db.models import Company, DashboardUser, UserRole
from app.db.session import get_session
from app.providers.kv import get_kv_store
from app.providers.kv.base import KVStore
from app.services.dashboard_session import COOKIE_NAME
from app.services.dashboard_session import get_session as get_dashboard_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
KVDep = Annotated[KVStore, Depends(get_kv_store)]


async def require_admin(
    x_admin_key: Annotated[str | None, Header()] = None,
) -> None:
    admin_key = get_settings().admin_api_key
    if not admin_key:
        raise HTTPException(
            status_code=503,
            detail="This endpoint is disabled: set ADMIN_API_KEY in .env and restart.",
        )
    if not x_admin_key or not keys_match(x_admin_key, admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key (X-Admin-Key).")


AdminDep = Annotated[None, Depends(require_admin)]


async def get_current_company(
    session: SessionDep,
    x_api_key: Annotated[str | None, Header()] = None,
) -> Company:
    company = await company_for_api_key(session, x_api_key) if x_api_key else None
    if company is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Pass the company key from "
            "POST /api/v1/companies in the X-API-Key header.",
        )
    return company


CompanyDep = Annotated[Company, Depends(get_current_company)]


async def get_chat_company(
    session: SessionDep,
    x_api_key: Annotated[str | None, Header()] = None,
    x_site_key: Annotated[str | None, Header()] = None,
    origin: Annotated[str | None, Header()] = None,
) -> Company:
    """Visitor-facing auth: secret X-API-Key, or public X-Site-Key + Origin allowlist."""
    if x_api_key:
        company = await company_for_api_key(session, x_api_key)
        if company is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid API key. Pass the company key from "
                "POST /api/v1/companies in the X-API-Key header.",
            )
        return company
    if x_site_key:
        company = await company_for_site_key(session, x_site_key)
        if company is None:
            raise HTTPException(
                status_code=401,
                detail="Invalid site key. Use the site_key returned by "
                "POST /api/v1/companies in the X-Site-Key header.",
            )
        if not company.allowed_domains:
            raise HTTPException(
                status_code=403,
                detail="This site key has no allowed domains yet. Configure them with "
                "PUT /api/v1/companies/domains using the secret X-API-Key, e.g. "
                '{"domains": ["example.com", "*.example.com"]}.',
            )
        host = origin_host(origin)
        if host is None:
            raise HTTPException(
                status_code=403,
                detail="Site-key requests must come from a browser page and send an "
                "Origin header. No valid Origin was received.",
            )
        if not domain_allowed(host, company.allowed_domains):
            raise HTTPException(
                status_code=403,
                detail=f"Origin '{host}' is not allowed for this site key. Allowed "
                f"domains: {', '.join(company.allowed_domains)}. Update them with "
                "PUT /api/v1/companies/domains using the secret X-API-Key.",
            )
        return company
    raise HTTPException(
        status_code=401,
        detail="Missing credentials. Pass X-Site-Key (browser widget) or "
        "X-API-Key (server-side) header.",
    )


ChatCompanyDep = Annotated[Company, Depends(get_chat_company)]


@dataclass
class DashboardAuth:
    user: DashboardUser
    company: Company
    csrf: str
    token: str


async def require_dashboard_auth(
    request: Request, session: SessionDep, kv: KVDep
) -> DashboardAuth:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=401, detail="Not signed in. POST /api/v1/auth/login first."
        )
    try:
        data = await get_dashboard_session(kv, token)
    except (RedisError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Session backend unavailable ({exc}). Check REDIS_URL / the Redis service.",
        ) from exc
    if data is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid. Sign in again.")
    user = await session.get(DashboardUser, data.user_id)
    if user is None or user.company_id != data.company_id:
        raise HTTPException(status_code=401, detail="Session expired or invalid. Sign in again.")
    company = await session.get(Company, data.company_id)
    if company is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid. Sign in again.")
    return DashboardAuth(user=user, company=company, csrf=data.csrf, token=token)


DashboardAuthDep = Annotated[DashboardAuth, Depends(require_dashboard_auth)]


async def require_owner(auth: DashboardAuthDep) -> DashboardAuth:
    if auth.user.role != UserRole.OWNER:
        raise HTTPException(
            status_code=403,
            detail="This action requires the owner role. Viewers have read-only access.",
        )
    return auth


OwnerDep = Annotated[DashboardAuth, Depends(require_owner)]


async def require_csrf(
    request: Request, auth: DashboardAuthDep, x_csrf_token: Annotated[str | None, Header()] = None
) -> None:
    if not x_csrf_token or not keys_match(x_csrf_token, auth.csrf):
        raise HTTPException(
            status_code=403,
            detail="Missing or invalid CSRF token. Send the csrf_token from "
            "GET /api/v1/auth/me in the X-CSRF-Token header.",
        )


CsrfDep = Annotated[None, Depends(require_csrf)]