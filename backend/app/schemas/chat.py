import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    stream: bool = False
    conversation_id: uuid.UUID | None = None
    language: Literal["ar", "fr", "en"] | None = None
    # Widget bot deterrent (site-key path only): hidden honeypot that must
    # stay empty, and the epoch-ms time the visitor opened the panel.
    website: str = ""
    opened_at: float | None = None

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value.strip()


class Citation(BaseModel):
    index: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int | None = None
    heading: str | None = None


class ChatResponse(BaseModel):
    answer: str
    model: str
    provider: str
    language: str
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    citations: list[Citation]