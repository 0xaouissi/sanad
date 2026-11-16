from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.db.models import DocumentStatus


class DocumentOut(BaseModel):
    id: UUID
    filename: str
    size_bytes: int
    status: DocumentStatus
    error: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class DocumentAccepted(BaseModel):
    id: UUID
    filename: str
    status: DocumentStatus
    duplicate_of: UUID | None = None