from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.security import normalize_domains, validate_chat_id, validate_handoff_email


class DashboardSettings(BaseModel):
    company_name: str
    site_key: str
    allowed_domains: list[str]
    store_conversations: bool
    handoff_email: str | None
    telegram_chat_id: str | None
    # Server-level transport availability (booleans only — never the secrets).
    smtp_configured: bool
    telegram_configured: bool


class SettingsUpdate(BaseModel):
    allowed_domains: list[str] | None = Field(default=None, max_length=50)
    store_conversations: bool | None = None
    # "" clears the destination; None leaves it unchanged.
    handoff_email: str | None = Field(default=None, max_length=320)
    telegram_chat_id: str | None = Field(default=None, max_length=64)

    @field_validator("allowed_domains")
    @classmethod
    def _normalize(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_domains(value)

    @field_validator("handoff_email")
    @classmethod
    def _clean_handoff_email(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return "" if value is not None else None
        return validate_handoff_email(value)

    @field_validator("telegram_chat_id")
    @classmethod
    def _clean_chat_id(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return "" if value is not None else None
        return validate_chat_id(value)


class KeyRotation(BaseModel):
    api_key: str = Field(description="Secret. Shown once; the previous key stops working.")
    site_key: str = Field(description="Public widget key; update the embedded snippet.")


class FailedQuestion(BaseModel):
    message_id: UUID
    conversation_id: UUID
    question: str
    language: str | None
    created_at: datetime


class RatingOut(BaseModel):
    message_id: UUID
    rating: str
    question: str | None
    answer: str
    language: str | None
    created_at: datetime


class RatingsSummary(BaseModel):
    up: int
    down: int
    items: list[RatingOut]


class DeletedCount(BaseModel):
    deleted: int