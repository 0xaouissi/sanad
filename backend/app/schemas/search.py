from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


class SearchHit(BaseModel):
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_number: int | None
    heading: str | None
    content: str
    score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]