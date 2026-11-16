from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import company_for_api_key
from app.db.models import Company
from app.db.session import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_company(
    session: SessionDep,
    x_api_key: Annotated[str, Header()],
) -> Company:
    company = await company_for_api_key(session, x_api_key)
    if company is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key. Pass the company key from POST /api/v1/companies "
            "in the X-API-Key header.",
        )
    return company


CompanyDep = Annotated[Company, Depends(get_current_company)]