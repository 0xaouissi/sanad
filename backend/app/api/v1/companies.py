from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from app.api.deps import CompanyDep, SessionDep
from app.core.config import get_settings
from app.core.passwords import hash_password
from app.core.security import (
    generate_api_key,
    generate_site_key,
    hash_api_key,
    keys_match,
    normalize_domains,
)
from app.db.models import Company, DashboardUser, UserRole
from app.schemas.company import CompanyCreate, CompanyCreated, DomainsResponse, DomainsUpdate

router = APIRouter(prefix="/companies", tags=["companies"])


@router.post("", response_model=CompanyCreated, status_code=201)
async def create_company(
    body: CompanyCreate,
    session: SessionDep,
    x_admin_key: Annotated[str, Header()],
) -> CompanyCreated:
    admin_key = get_settings().admin_api_key
    if not admin_key:
        raise HTTPException(
            status_code=503,
            detail="Company creation is disabled: set ADMIN_API_KEY in .env and restart.",
        )
    if not keys_match(x_admin_key, admin_key):
        raise HTTPException(status_code=401, detail="Invalid admin key (X-Admin-Key).")
    if body.owner_email is not None:
        existing = await session.scalar(
            select(DashboardUser).where(DashboardUser.email == body.owner_email)
        )
        if existing is not None:
            raise HTTPException(
                status_code=409, detail="owner_email already has an account."
            )
    api_key = generate_api_key()
    company = Company(
        name=body.name, api_key_hash=hash_api_key(api_key), site_key=generate_site_key()
    )
    session.add(company)
    await session.flush()
    if body.owner_email is not None:
        session.add(
            DashboardUser(
                company_id=company.id,
                email=body.owner_email,
                password_hash=hash_password(body.owner_password),
                role=UserRole.OWNER,
            )
        )
    await session.commit()
    return CompanyCreated(
        id=company.id, name=company.name, api_key=api_key, site_key=company.site_key
    )


@router.put("/domains", response_model=DomainsResponse)
async def set_allowed_domains(
    body: DomainsUpdate, company: CompanyDep, session: SessionDep
) -> DomainsResponse:
    try:
        company.allowed_domains = normalize_domains(body.domains)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return DomainsResponse(domains=company.allowed_domains)