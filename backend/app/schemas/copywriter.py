from __future__ import annotations

from pydantic import BaseModel, Field


class CopywriterGenerateRequest(BaseModel):
    product: str = Field(..., min_length=1, max_length=500, description="Product name or description")
    brand: str | None = Field(default=None, max_length=200, description="Brand name if known")
    country: str = Field(default="Argentina", max_length=100, description="Target country")
    confirmed_data: str | None = Field(default=None, max_length=2000, description="Known real data about the product")
    commercial_objective: str | None = Field(
        default=None,
        max_length=500,
        description="E.g. Mercado Libre, Instagram, tienda propia",
    )


class CopywriterGenerateResponse(BaseModel):
    titles: list[str] = Field(default_factory=list, description="10 suggested titles")
    description: str = Field(default="", description="Full formatted description")


class DescriptionEnhanceRequest(BaseModel):
    product_title: str = Field(..., min_length=1, max_length=500)
    current_description: str = Field(default="", max_length=10000)
    brand: str | None = None
    category: str | None = None
    price: float | None = None
    currency: str | None = None
    condition: str | None = None
    attributes: list[dict] = Field(default_factory=list)
    improvement_notes: str | None = Field(default=None, max_length=3000)


class DescriptionEnhanceResponse(BaseModel):
    enhanced_description: str = Field(default="", description="AI-improved description")
