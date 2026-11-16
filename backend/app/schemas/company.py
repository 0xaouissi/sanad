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
    api_key: str = Field(description="Secret. Shown once at creation; store it securely.")
    site_key: str = Field(description="Public widget key; restricted to allowed_domains.")


class DomainsUpdate(BaseModel):
    domains: list[str] = Field(max_length=50)


class DomainsResponse(BaseModel):
    domains: list[str]