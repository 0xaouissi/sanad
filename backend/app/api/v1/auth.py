from fastapi import APIRouter, HTTPException, Request, Response
from redis.exceptions import RedisError
from sqlalchemy import select

from app.api.deps import CsrfDep, DashboardAuthDep, KVDep, SessionDep
from app.core.config import get_settings
from app.core.passwords import DUMMY_HASH, verify_password
from app.db.models import Company, DashboardUser
from app.schemas.auth import CompanyInfo, LoginRequest, SessionResponse, UserInfo
from app.services.dashboard_session import (
    clear_session_cookie,
    create_session,
    delete_session,
    set_session_cookie,
)
from app.services.rate_limit import enforce_login_limit

router = APIRouter(prefix="/auth", tags=["auth"])


def _session_response(auth_user: DashboardUser, company: Company, csrf: str) -> SessionResponse:
    return SessionResponse(
        user=UserInfo(id=auth_user.id, email=auth_user.email, role=auth_user.role),
        company=CompanyInfo(id=company.id, name=company.name),
        csrf_token=csrf,
    )


@router.post("/login", response_model=SessionResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: SessionDep,
    kv: KVDep,
) -> SessionResponse:
    settings = get_settings()
    await enforce_login_limit(kv, request, settings)
    user = await session.scalar(select(DashboardUser).where(DashboardUser.email == body.email))
    # Verify against a dummy hash when the email is unknown so timing does
    # not reveal whether an account exists.
    stored = user.password_hash if user is not None else DUMMY_HASH
    if not verify_password(body.password, stored) or user is None:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    try:
        token, data = await create_session(kv, user.id, user.company_id, settings)
    except (RedisError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Session backend unavailable ({exc}). Check REDIS_URL / the Redis service.",
        ) from exc
    set_session_cookie(response, token, settings)
    company = await session.get(Company, user.company_id)
    return _session_response(user, company, data.csrf)


@router.post("/logout")
async def logout(
    response: Response, auth: DashboardAuthDep, kv: KVDep, _: CsrfDep
) -> dict[str, str]:
    settings = get_settings()
    try:
        await delete_session(kv, auth.token)
    except (RedisError, OSError):
        pass  # The cookie is cleared either way; the KV entry expires on its own.
    clear_session_cookie(response, settings)
    return {"detail": "Signed out."}


@router.get("/me", response_model=SessionResponse)
async def me(auth: DashboardAuthDep) -> SessionResponse:
    return _session_response(auth.user, auth.company, auth.csrf)