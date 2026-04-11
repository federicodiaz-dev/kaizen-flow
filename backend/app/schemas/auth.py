from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.plans import PlanSummary


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    username: str | None = Field(default=None, min_length=3, max_length=40)
    password: str = Field(..., min_length=12, max_length=256)
    selected_plan_code: str | None = Field(default=None, min_length=1, max_length=40)


class LoginRequest(BaseModel):
    login: str | None = Field(default=None, min_length=3, max_length=320)
    email: str | None = Field(default=None, min_length=5, max_length=320)
    password: str = Field(..., min_length=8, max_length=256)


class UserProfile(BaseModel):
    id: int
    email: str
    username: str
    created_at: str
    is_first_visit: bool = False
    default_account: str | None = None
    current_plan: PlanSummary | None = None


class SessionResponse(BaseModel):
    user: UserProfile


class MercadoLibreConnectResponse(BaseModel):
    authorization_url: str


class MercadoLibreCompleteRequest(BaseModel):
    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_description: str | None = None


class MercadoLibreCompleteResponse(BaseModel):
    account_key: str
    account_label: str
    ml_user_id: int


class DefaultAccountRequest(BaseModel):
    account_key: str = Field(..., min_length=1, max_length=80)
