"""Human handoff (Step 6c): deliver a visitor's request to the company.

Channels are email (SMTP) and Telegram, both configured server-side through
environment settings — secrets never touch the database or the API. The
company chooses destinations in dashboard Settings. Requests are persisted
only while the company stores conversations (privacy toggle).
"""

import asyncio
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formatdate

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import clean_header_text
from app.db.models import ChannelStatus, Company, HandoffRequest
from app.rag.language import detect_language

log = structlog.get_logger()

# Telegram sendMessage caps text at 4096 characters.
_TELEGRAM_MAX_TEXT = 4096


class HandoffError(Exception):
    def __init__(self, detail: str, status_code: int = 502) -> None:
        super().__init__(detail)
        self.status_code = status_code


@dataclass
class HandoffOutcome:
    email: ChannelStatus
    telegram: ChannelStatus
    stored: bool


def plan_channels(company: Company, settings: Settings) -> tuple[bool, bool]:
    return (
        bool(company.handoff_email and settings.smtp_host),
        bool(company.telegram_chat_id and settings.telegram_bot_token),
    )


def _not_configured_error(company: Company, settings: Settings) -> HandoffError:
    if not company.handoff_email and not company.telegram_chat_id:
        return HandoffError(
            "Human handoff is not set up for this company. The owner must add a "
            "support email or a Telegram chat id in dashboard Settings.",
            409,
        )
    missing = []
    if company.handoff_email and not settings.smtp_host:
        missing.append("SMTP_HOST and SMTP_FROM in the server environment for email")
    if company.telegram_chat_id and not settings.telegram_bot_token:
        missing.append("TELEGRAM_BOT_TOKEN in the server environment for Telegram")
    return HandoffError(
        "Handoff destinations are set but the server transport is missing: "
        + "; ".join(missing)
        + ". Configure it and restart the app.",
        409,
    )


def build_email(
    company: Company,
    visitor_email: str,
    message: str,
    language: str | None,
    settings: Settings,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = clean_header_text(company.handoff_email or "")
    # The company replies straight to the visitor.
    msg["Reply-To"] = visitor_email
    msg["Subject"] = (
        f"[{clean_header_text(settings.app_name)}] Human help request"
        f" — {clean_header_text(company.name)}"
    )
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(
        f"A visitor asked for a human on {clean_header_text(company.name)}.\n\n"
        f"Reply to: {visitor_email}\n"
        f"Language: {language or 'unknown'}\n"
        f"Received: {datetime.now(UTC).isoformat(timespec='seconds')}\n\n"
        f"Message:\n{message}\n"
    )
    return msg


def _send_email_sync(msg: EmailMessage, settings: Settings) -> None:
    with smtplib.SMTP(
        settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
    ) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


async def send_email(msg: EmailMessage, settings: Settings) -> None:
    try:
        await asyncio.to_thread(_send_email_sync, msg, settings)
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("handoff_email_failed", detail=str(exc))
        raise HandoffError(
            f"Could not send the handoff email via {settings.smtp_host}:{settings.smtp_port} "
            f"({exc.__class__.__name__}). Check SMTP_HOST, SMTP_PORT, SMTP_USER, "
            "SMTP_PASSWORD and SMTP_STARTTLS, and that the relay accepts mail "
            "for the recipient domain."
        ) from exc


def telegram_text(
    company: Company, visitor_email: str, message: str, language: str | None
) -> str:
    text = (
        f"Human help request — {clean_header_text(company.name)}\n"
        f"Visitor: {visitor_email}\n"
        f"Language: {language or 'unknown'}\n\n"
        f"{message}"
    )
    return text[:_TELEGRAM_MAX_TEXT]


async def send_telegram(
    company: Company,
    visitor_email: str,
    message: str,
    language: str | None,
    settings: Settings,
) -> None:
    # The token is part of the URL: never log or echo it.
    url = (
        f"{settings.telegram_api_base.rstrip('/')}"
        f"/bot{settings.telegram_bot_token}/sendMessage"
    )
    payload = {
        "chat_id": company.telegram_chat_id,
        "text": telegram_text(company, visitor_email, message, language),
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(
            timeout=settings.telegram_timeout_seconds, trust_env=False
        ) as client:
            response = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        log.warning("handoff_telegram_unreachable", detail=exc.__class__.__name__)
        raise HandoffError(
            f"Could not reach Telegram ({exc.__class__.__name__}). Check outbound "
            "network access and TELEGRAM_API_BASE."
        ) from exc
    if response.status_code != 200:
        log.warning("handoff_telegram_rejected", status=response.status_code)
        raise HandoffError(
            f"Telegram rejected the message (HTTP {response.status_code}). Check "
            "TELEGRAM_BOT_TOKEN and the company's Telegram chat id in Settings."
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise HandoffError(
            "Telegram returned an unexpected response. Check TELEGRAM_API_BASE."
        ) from exc
    if not data.get("ok"):
        description = str(data.get("description", "unknown error"))
        log.warning("handoff_telegram_not_ok", description=description)
        raise HandoffError(
            f"Telegram rejected the message: {description}. The bot must have "
            "been messaged first (or be a member of the group) — check the "
            "company's Telegram chat id in Settings."
        )


async def request_handoff(
    session: AsyncSession,
    company: Company,
    email: str,
    message: str,
    language: str | None,
    settings: Settings,
) -> HandoffOutcome:
    email_on, telegram_on = plan_channels(company, settings)
    if not email_on and not telegram_on:
        raise _not_configured_error(company, settings)
    lang = language or detect_language(message)
    errors: list[str] = []
    email_status = ChannelStatus.SKIPPED
    telegram_status = ChannelStatus.SKIPPED
    if email_on:
        try:
            await send_email(build_email(company, email, message, lang, settings), settings)
            email_status = ChannelStatus.SENT
        except HandoffError as exc:
            email_status = ChannelStatus.FAILED
            errors.append(str(exc))
    if telegram_on:
        try:
            await send_telegram(company, email, message, lang, settings)
            telegram_status = ChannelStatus.SENT
        except HandoffError as exc:
            telegram_status = ChannelStatus.FAILED
            errors.append(str(exc))
    stored = False
    if company.store_conversations:
        session.add(
            HandoffRequest(
                company_id=company.id,
                email=email,
                message=message,
                language=lang,
                email_status=email_status,
                telegram_status=telegram_status,
                error="; ".join(errors) or None,
            )
        )
        await session.commit()
        stored = True
    if email_status is not ChannelStatus.SENT and telegram_status is not ChannelStatus.SENT:
        raise HandoffError(
            "Could not deliver the handoff request: " + "; ".join(errors), 502
        )
    return HandoffOutcome(email=email_status, telegram=telegram_status, stored=stored)