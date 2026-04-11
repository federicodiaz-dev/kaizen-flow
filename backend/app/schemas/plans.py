from __future__ import annotations

from pydantic import BaseModel, Field


class PlanSummary(BaseModel):
    code: str
    name: str
    headline: str
    status: str
    price_monthly: int
    currency: str
    max_accounts: int
    reply_assistant_limit: int | None = None
    listing_doctor_limit: int | None = None


class PlanCatalogItem(BaseModel):
    code: str
    name: str
    headline: str
    description: str
    price_monthly: int
    currency: str
    max_accounts: int
    reply_assistant_limit: int | None = None
    listing_doctor_limit: int | None = None
    features: list[str] = Field(default_factory=list)
    sort_order: int


class PlanCatalogResponse(BaseModel):
    plans: list[PlanCatalogItem]


class SelectPlanRequest(BaseModel):
    plan_code: str = Field(..., min_length=1, max_length=40)
