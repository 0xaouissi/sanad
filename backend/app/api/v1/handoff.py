from fastapi import APIRouter, HTTPException, Request

from app.api.deps import ChatCompanyDep, KVDep, SessionDep
from app.core.config import get_settings
from app.schemas.handoff import HandoffRequestIn, HandoffResponse
from app.services.bot_check import enforce_bot_check
from app.services.handoff import HandoffError, request_handoff
from app.services.rate_limit import enforce_handoff_limits

router = APIRouter(tags=["handoff"])


@router.post("/handoff", response_model=HandoffResponse)
async def handoff(
    body: HandoffRequestIn,
    raw_request: Request,
    company: ChatCompanyDep,
    session: SessionDep,
    kv: KVDep,
) -> HandoffResponse:
    settings = get_settings()
    # Mirrors get_chat_company: the secret key wins when both are present.
    via_site_key = "x-site-key" in raw_request.headers and "x-api-key" not in raw_request.headers
    enforce_bot_check(body, via_site_key, settings)
    await enforce_handoff_limits(kv, raw_request, company.id, settings)
    try:
        outcome = await request_handoff(
            session, company, body.email, body.message, body.language, settings
        )
    except HandoffError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return HandoffResponse(
        email=outcome.email, telegram=outcome.telegram, stored=outcome.stored
    )