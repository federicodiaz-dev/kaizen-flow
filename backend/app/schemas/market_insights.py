from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ResolutionStage = Literal["category_predictor", "search_fallback", "public_listing_inference"]
ResolutionStatus = Literal["ok", "empty", "error"]
SearchScope = Literal["category", "site", "web_listing", "web_category_listing"]
ValidationStatus = Literal["validated"]
MarketInsightsTracePhase = Literal["started", "completed", "failed", "info"]


class MarketTrendReportRequest(BaseModel):
    natural_query: str = Field(..., min_length=2, max_length=200)
    site_id: str | None = Field(default=None, min_length=3, max_length=4)
    limit: int = Field(default=5, ge=1, le=8)


class MarketInsightsTraceEntry(BaseModel):
    sequence: int
    timestamp: str
    stage: str
    phase: MarketInsightsTracePhase
    message: str
    details: dict | list | str | None = None


class MarketTrendResolutionNote(BaseModel):
    stage: ResolutionStage
    query_used: str
    status: ResolutionStatus
    suggestion_count: int | None = None
    category_count: int | None = None
    message: str | None = None


class MarketResolvedCategory(BaseModel):
    category_id: str
    category_name: str | None = None
    domain_id: str | None = None
    domain_name: str | None = None
    resolved_by: str
    query_used: str
    search_hit_count: int | None = None
    fallback_titles: list[str] = Field(default_factory=list)
    category_path: list[str] = Field(default_factory=list)
    category_depth: int = 0
    is_low_signal_category: bool = False


class MarketPriceStats(BaseModel):
    min: float | None = None
    max: float | None = None
    avg: float | None = None
    median: float | None = None


class MarketSampleResult(BaseModel):
    id: str | None = None
    title: str | None = None
    price: float | None = None
    currency_id: str | None = None
    sold_quantity: int | None = None
    permalink: str | None = None


class MarketOpportunityEvidence(BaseModel):
    search_scope: SearchScope
    total_results: int | None = None
    sample_result_count: int = 0
    matching_title_count: int = 0
    price_stats: MarketPriceStats = Field(default_factory=MarketPriceStats)
    avg_sold_quantity: float | None = None
    sample_titles: list[str] = Field(default_factory=list)
    sample_results: list[MarketSampleResult] = Field(default_factory=list)


class MarketValidatedOpportunity(BaseModel):
    keyword: str
    category_id: str | None = None
    category_name: str | None = None
    category_path: list[str] = Field(default_factory=list)
    trend_bucket: str
    trend_rank: int
    validation_status: ValidationStatus = "validated"
    specificity_score: float
    evidence_score: float
    ranking_score: float
    justification: str
    risk_flags: list[str] = Field(default_factory=list)
    market_evidence: MarketOpportunityEvidence


class MarketDiscardedSignal(BaseModel):
    keyword: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    reason: str


class MarketTrendReportSummary(BaseModel):
    resolved_category_count: int = 0
    validated_opportunity_count: int = 0
    discarded_signal_count: int = 0


class MarketTrendReportResponse(BaseModel):
    ok: bool = True
    run_id: str | None = None
    site_id: str
    input_query: str
    resolution_notes: list[MarketTrendResolutionNote] = Field(default_factory=list)
    resolved_categories: list[MarketResolvedCategory] = Field(default_factory=list)
    validated_opportunities: list[MarketValidatedOpportunity] = Field(default_factory=list)
    discarded_signals: list[MarketDiscardedSignal] = Field(default_factory=list)
    summary: MarketTrendReportSummary = Field(default_factory=MarketTrendReportSummary)
    execution_trace: list[MarketInsightsTraceEntry] = Field(default_factory=list)
    log_file_path: str | None = None
