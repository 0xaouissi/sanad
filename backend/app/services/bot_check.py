"""Widget bot deterrent: hidden honeypot field + minimum panel-open time.

Enforced only on the public site-key path; server-side X-API-Key callers
are exempt. This raises the cost of trivial bots — it is not a security
boundary, since a determined script can fill the fields correctly.
"""

import math
import time

from fastapi import HTTPException

from app.core.config import Settings
from app.schemas.chat import ChatRequest
from app.schemas.handoff import HandoffRequestIn


def enforce_bot_check(
    request: ChatRequest | HandoffRequestIn, via_site_key: bool, settings: Settings
) -> None:
    if not via_site_key or not settings.bot_check_enabled:
        return
    if request.website.strip():
        raise HTTPException(
            status_code=400,
            detail="Bot check failed: the hidden 'website' field must stay empty.",
        )
    if request.opened_at is None:
        raise HTTPException(
            status_code=400,
            detail="Bot check failed: missing 'opened_at'. Send chat requests "
            "through the official widget.",
        )
    elapsed = time.time() - request.opened_at / 1000.0
    if elapsed < settings.bot_check_min_seconds:
        retry = max(1, math.ceil(settings.bot_check_min_seconds - elapsed))
        raise HTTPException(
            status_code=429,
            detail=f"Bot check failed: please wait a moment before sending "
            f"(retry in {retry} seconds).",
            headers={"Retry-After": str(retry)},
        )