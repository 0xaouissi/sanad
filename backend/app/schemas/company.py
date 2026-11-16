from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Optional dashboard owner, created with the company. Both or neither.
    owner_email: str | None = Field(default=None, min_length=3, max_length=320)
    owner_password: str | None = Field(default=None, min_length=8, max_length=200)

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value.strip()

    @field_validator("owner_email")
    @classmethod
    def _clean_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        email = value.strip().lower()
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("owner_email must be a valid address like name@example.com")
        return email

    @model_validator(mode="after")
    def _owner_pair(self) -> "CompanyCreate":
        if (self.owner_email is None) != (self.owner_password is None):
            raise ValueError("owner_email and owner_password must be provided together")
        return self


class CompanyCreated(BaseModel):
    id: UUID
    name: str
    api_key: str = Field(description="Secret. Shown once at creation; store it securely.")
    site_key: str = Field(description="Public widget key; restricted to allowed_domains.")


class DomainsUpdate(BaseModel):
    domains: list[str] = Field(max_length=50)


class DomainsResponse(BaseModel):
    domains: list[str]