from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypedDict


ProgressHook = Callable[[str, str, str | None], Awaitable[None]]
TraceHook = Callable[[str, str, str, str, Any | None], Awaitable[None]]


class ListingDoctorState(TypedDict, total=False):
    job_id: str
    account_key: str
    site_id: str
    item_id: str
    include_copywriter: bool
    competitor_limit: int
    search_depth: int
    progress_hook: ProgressHook
    trace_hook: TraceHook
    warnings: list[str]
    raw_listing: dict[str, Any]
    listing: dict[str, Any]
    normalized_listing: dict[str, Any]
    product_signals: dict[str, Any]
    query_bundle: dict[str, Any]
    search_runs: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    shortlisted_candidates: list[dict[str, Any]]
    competitor_features: list[dict[str, Any]]
    market_summary: dict[str, Any]
    scores: dict[str, float]
    findings: dict[str, Any]
    actions: list[dict[str, Any]]
    evidence: dict[str, list[str]]
    executive_summary: str
    detailed_diagnosis: list[str]
    ai_suggestions: dict[str, Any]
    copywriter_context: dict[str, Any]
    partial_analysis: bool
    result: dict[str, Any]
