from __future__ import annotations

from pydantic import BaseModel


class AccountSummary(BaseModel):
    key: str
    label: str
    source: str
    user_id: int | None = None
    scope: str | None = None
    is_default: bool
    is_active: bool


class AccountsResponse(BaseModel):
    default_account: str | None = None
    items: list[AccountSummary]


class DefaultAccountResponse(BaseModel):
    default_account: str
