from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.security import normalize_domains


class DashboardSettings(BaseModel):
    company_name: str
    site_key: str
    allowed_domains: list[str]
    store_conversations: bool


class SettingsUpdate(BaseModel):
    allowed_domains: list[str] | None = Field(default=None, max_length=50)
    store_conversations: bool | None = None

    @field_validator("allowed_domains")
    @classmethod
    def _normalize(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else normalize_domains(value)


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