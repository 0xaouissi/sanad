from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.security import validate_handoff_email
from app.db.models import ChannelStatus


class HandoffRequestIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    message: str = Field(min_length=1, max_length=4000)
    language: Literal["ar", "fr", "en"] | None = None
    # Widget bot deterrent (site-key path only), same fields as chat.
    website: str = ""
    opened_at: float | None = None

    @field_validator("email")
    @classmethod
    def _clean_email(cls, value: str) -> str:
        return validate_handoff_email(value)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        if "\x00" in value:
            raise ValueError("message must not contain NUL characters")
        return value.strip()


class HandoffResponse(BaseModel):
    email: ChannelStatus
    telegram: ChannelStatus
    # False when the company disabled conversation storage (privacy control).
    stored: bool


class HandoffOut(BaseModel):
    id: UUID
    email: str
    message: str
    language: str | None
    email_status: ChannelStatus
    telegram_status: ChannelStatus
    error: str | None
    created_at: datetime