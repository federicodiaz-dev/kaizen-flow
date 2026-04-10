from __future__ import annotations

from pydantic import BaseModel


class PublicPlan(BaseModel):
    code: str
    name: str
    description: str
    price_cents: int
    currency: str
    price_label: str
    badge: str | None = None
    is_recommended: bool
    features: list[str]


class PublicPlansResponse(BaseModel):
    app_url: str
    items: list[PublicPlan]
