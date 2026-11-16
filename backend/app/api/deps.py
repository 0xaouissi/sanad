from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    company_for_api_key,
    company_for_site_key,
    domain_allowed,
    keys_match,
    origin_host,
)
from app.db.models import Company
from app.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


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