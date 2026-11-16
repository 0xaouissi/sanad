from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()


class CompanyCreated(BaseModel):
    id: UUID
    name: str
    api_key: str = Field(description="Shown once at creation; store it securely.")