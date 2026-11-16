from typing import Annotated

from fastapi import APIRouter, Header, HTTPException

from app.api.deps import SessionDep
from app.core.config import get_settings
from app.core.security import generate_api_key, hash_api_key, keys_match
from app.db.models import Company
from app.schemas.company import CompanyCreate, CompanyCreated

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
    api_key = generate_api_key()
    company = Company(name=body.name, api_key_hash=hash_api_key(api_key))
    session.add(company)
    await session.commit()
    return CompanyCreated(id=company.id, name=company.name, api_key=api_key)