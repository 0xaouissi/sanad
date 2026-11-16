from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _clean_email(value: str) -> str:
    email = value.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ValueError("email must be a valid address like name@example.com")
    return email


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return _clean_email(value)


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return _clean_email(value)


class UserInfo(BaseModel):
    id: UUID
    email: str
    role: str


class CompanyInfo(BaseModel):
    id: UUID
    name: str


class SessionResponse(BaseModel):
    user: UserInfo
    company: CompanyInfo
    csrf_token: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: str
    created_at: datetime