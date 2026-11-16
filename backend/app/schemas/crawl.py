from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import CrawlStatus


class CrawlSourceCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class CrawlSourceOut(BaseModel):
    id: UUID
    url: str
    status: CrawlStatus
    error: str | None
    pages_crawled: int
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime