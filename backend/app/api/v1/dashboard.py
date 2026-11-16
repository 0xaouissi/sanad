from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CsrfDep, OwnerDep, SessionDep
from app.core.passwords import hash_password
from app.db.models import DashboardUser, UserRole
from app.schemas.auth import UserCreate, UserResponse

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(auth: OwnerDep, session: SessionDep) -> list[UserResponse]:
    users = await session.scalars(
        select(DashboardUser)
        .where(DashboardUser.company_id == auth.company.id)
        .order_by(DashboardUser.created_at)
    )
    return [
        UserResponse(id=u.id, email=u.email, role=u.role, created_at=u.created_at) for u in users
    ]


@router.post("/users", response_model=UserResponse, status_code=201)
async def add_viewer(
    body: UserCreate, auth: OwnerDep, session: SessionDep, _: CsrfDep
) -> UserResponse:
    existing = await session.scalar(select(DashboardUser).where(DashboardUser.email == body.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="This email already has an account.")
    user = DashboardUser(
        company_id=auth.company.id,
        email=body.email,
        password_hash=hash_password(body.password),
        role=UserRole.VIEWER,
    )
    session.add(user)
    await session.commit()
    return UserResponse(id=user.id, email=user.email, role=user.role, created_at=user.created_at)