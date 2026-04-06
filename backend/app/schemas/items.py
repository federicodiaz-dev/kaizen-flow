from __future__ import annotations

from pydantic import BaseModel, Field


class ItemSummary(BaseModel):
    id: str
    title: str
    price: float | None = None
    currency_id: str | None = None
    available_quantity: int | None = None
    sold_quantity: int | None = None
    status: str | None = None
    permalink: str | None = None
    thumbnail: str | None = None
    last_updated: str | None = None


class ItemDetail(ItemSummary):
    seller_id: int | None = None
    category_id: str | None = None
    listing_type_id: str | None = None
    condition: str | None = None
    health: str | None = None
    variations: list[dict] = []
    attributes: list[dict] = []
    pictures: list[dict] = []


class ItemListResponse(BaseModel):
    items: list[ItemSummary]
    total: int
    offset: int
    limit: int


class ItemUpdatePayload(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=120)
    price: float | None = Field(default=None, gt=0)
    available_quantity: int | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern="^(active|paused|closed)$")
