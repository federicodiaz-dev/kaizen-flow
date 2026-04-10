from __future__ import annotations

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=256)
    workspace_name: str | None = Field(default=None, min_length=2, max_length=120)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=256)


class WorkspaceProfile(BaseModel):
    id: str
    name: str
    slug: str
    role: str


class SubscriptionProfile(BaseModel):
    status: str
    plan_code: str | None = None
    plan_name: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    expires_at: str | None = None
    is_active: bool


class UserProfile(BaseModel):
    id: str
    email: str
    created_at: str
    is_first_visit: bool = False
    default_account: str | None = None


class SessionResponse(BaseModel):
    user: UserProfile
    workspace: WorkspaceProfile
    subscription: SubscriptionProfile
    csrf_token: str | None = None


class MercadoLibreConnectResponse(BaseModel):
    authorization_url: str


class DefaultAccountRequest(BaseModel):
    account_key: str = Field(..., min_length=1, max_length=80)
