from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ListingDoctorJobState = Literal["queued", "running", "partial", "completed", "failed", "interrupted"]
ListingDoctorStepState = Literal["pending", "running", "completed", "skipped", "failed"]
ListingDoctorTracePhase = Literal["started", "completed", "failed", "info"]
ActionPriority = Literal["high", "medium", "low"]
ActionImpact = Literal["high", "medium", "low"]
ActionEffort = Literal["low", "medium", "high"]
BenchmarkConfidence = Literal["low", "medium", "high"]


class ListingDoctorJobRequest(BaseModel):
    item_id: str = Field(..., min_length=3, max_length=40)
    site_id: str | None = Field(default=None, min_length=3, max_length=4)
    include_copywriter: bool = False
    competitor_limit: int = Field(default=8, ge=3, le=12)
    search_depth: int = Field(default=2, ge=1, le=3)


class ListingDoctorProgressStep(BaseModel):
    key: str
    label: str
    status: ListingDoctorStepState = "pending"
    message: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


class ListingDoctorTraceEntry(BaseModel):
    sequence: int
    timestamp: str
    agent: str
    node: str
    phase: ListingDoctorTracePhase
    message: str
    details: dict | list | str | None = None


class ListingDoctorListingSummary(BaseModel):
    item_id: str
    title: str
    status: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    site_id: str | None = None
    currency_id: str | None = None
    price: float | None = None
    sold_quantity: int | None = None
    available_quantity: int | None = None
    condition: str | None = None
    listing_type_id: str | None = None
    listing_exposure: str | None = None
    health: float | None = None
    health_actions: list[str] = Field(default_factory=list)
    brand: str | None = None
    product_type: str | None = None
    key_attributes: list[str] = Field(default_factory=list)
    missing_attributes: list[str] = Field(default_factory=list)
    attributes_count: int = 0
    pictures_count: int = 0
    description_present: bool = False
    description_length: int = 0
    thumbnail: str | None = None
    permalink: str | None = None
    last_updated: str | None = None


class ListingDoctorMarketSummary(BaseModel):
    total_candidates: int = 0
    shortlisted_competitors: int = 0
    query_count: int = 0
    median_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    priced_competitors: int = 0
    detailed_competitors: int = 0
    benchmark_confidence: BenchmarkConfidence = "low"
    price_benchmark_confidence: BenchmarkConfidence = "low"
    dominant_keywords: list[str] = Field(default_factory=list)
    dominant_brands: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)


class ListingDoctorScores(BaseModel):
    overall: float = Field(default=0.0, ge=0.0, le=100.0)
    title: float = Field(default=0.0, ge=0.0, le=100.0)
    price: float = Field(default=0.0, ge=0.0, le=100.0)
    attributes: float = Field(default=0.0, ge=0.0, le=100.0)
    description: float = Field(default=0.0, ge=0.0, le=100.0)
    competitiveness: float = Field(default=0.0, ge=0.0, le=100.0)
    opportunity: float = Field(default=0.0, ge=0.0, le=100.0)


class ListingDoctorCompetitorSnapshot(BaseModel):
    item_id: str
    title: str
    price: float | None = None
    currency_id: str | None = None
    sold_quantity: int | None = None
    status: str | None = None
    brand: str | None = None
    condition: str | None = None
    listing_type_id: str | None = None
    listing_exposure: str | None = None
    health: float | None = None
    attributes_count: int = 0
    description_present: bool = False
    recurrence: int = 0
    average_position: float | None = None
    similarity_score: float = Field(default=0.0, ge=0.0, le=100.0)
    strength_score: float = Field(default=0.0, ge=0.0, le=100.0)
    benchmark_score: float = Field(default=0.0, ge=0.0, le=100.0)
    growth_proxy: float | None = None
    selection_reason: str = ""
    signals: list[str] = Field(default_factory=list)
    thumbnail: str | None = None
    permalink: str | None = None
    last_updated: str | None = None


class ListingDoctorFindings(BaseModel):
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    missing_attributes: list[str] = Field(default_factory=list)
    pricing_position: list[str] = Field(default_factory=list)
    title_gaps: list[str] = Field(default_factory=list)
    description_gaps: list[str] = Field(default_factory=list)


class ListingDoctorAction(BaseModel):
    title: str
    summary: str
    priority: ActionPriority = "medium"
    impact: ActionImpact = "medium"
    effort: ActionEffort = "medium"
    tags: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class ListingDoctorAiSuggestions(BaseModel):
    suggested_titles: list[str] = Field(default_factory=list)
    suggested_description: str = ""
    positioning_strategy: str = ""


class ListingDoctorEvidence(BaseModel):
    factual_points: list[str] = Field(default_factory=list)
    proxy_points: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class ListingDoctorResult(BaseModel):
    listing: ListingDoctorListingSummary
    market_summary: ListingDoctorMarketSummary
    scores: ListingDoctorScores
    executive_summary: str = ""
    detailed_diagnosis: list[str] = Field(default_factory=list)
    competitor_snapshot: list[ListingDoctorCompetitorSnapshot] = Field(default_factory=list)
    findings: ListingDoctorFindings
    actions: list[ListingDoctorAction] = Field(default_factory=list)
    ai_suggestions: ListingDoctorAiSuggestions = Field(default_factory=ListingDoctorAiSuggestions)
    evidence: ListingDoctorEvidence = Field(default_factory=ListingDoctorEvidence)
    generated_at: str
    account_key: str
    site_id: str
    warnings: list[str] = Field(default_factory=list)
    execution_trace: list[ListingDoctorTraceEntry] = Field(default_factory=list)
    log_file_path: str | None = None


class ListingDoctorJobAccepted(BaseModel):
    job_id: str
    status: ListingDoctorJobState
    created_at: str
    updated_at: str
    account_key: str
    site_id: str
    item_id: str
    steps: list[ListingDoctorProgressStep] = Field(default_factory=list)
    trace: list[ListingDoctorTraceEntry] = Field(default_factory=list)
    log_file_path: str | None = None


class ListingDoctorJobStatus(BaseModel):
    job_id: str
    status: ListingDoctorJobState
    created_at: str
    updated_at: str
    account_key: str
    site_id: str
    item_id: str
    include_copywriter: bool = False
    competitor_limit: int = 8
    search_depth: int = 2
    error_message: str | None = None
    warnings: list[str] = Field(default_factory=list)
    steps: list[ListingDoctorProgressStep] = Field(default_factory=list)
    trace: list[ListingDoctorTraceEntry] = Field(default_factory=list)
    log_file_path: str | None = None
    result: ListingDoctorResult | None = None
