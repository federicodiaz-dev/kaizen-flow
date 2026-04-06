from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=256)


class UserProfile(BaseModel):
    id: int
    email: str
    created_at: str
    default_account: str | None = None


class SessionResponse(BaseModel):
    user: UserProfile


class MercadoLibreConnectResponse(BaseModel):
    authorization_url: str


class DefaultAccountRequest(BaseModel):
    account_key: str = Field(..., min_length=1, max_length=80)
