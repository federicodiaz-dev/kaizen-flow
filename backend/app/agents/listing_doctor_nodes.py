from __future__ import annotations

import asyncio
import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from statistics import median
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.adapters.market_research import MarketResearchAdapter
from app.agents.listing_doctor_prompts import (
    LISTING_NORMALIZER_PROMPT,
    POSITIONING_STRATEGY_PROMPT,
    QUERY_STRATEGIST_PROMPT,
    STRATEGY_SYNTHESIS_PROMPT,
)
from app.agents.listing_doctor_state import ListingDoctorState
from app.core.exceptions import AppError, MercadoLibreAPIError
from app.schemas.copywriter import CopywriterGenerateRequest, DescriptionEnhanceRequest
from app.schemas.listing_doctor import (
    ListingDoctorAction,
    ListingDoctorAiSuggestions,
    ListingDoctorCompetitorSnapshot,
    ListingDoctorEvidence,
    ListingDoctorFindings,
    ListingDoctorListingSummary,
    ListingDoctorMarketSummary,
    ListingDoctorResult,
    ListingDoctorScores,
)
from app.services.copywriter import CopywriterService
from app.services.items import ItemsService


SEARCH_DEPTH_CONFIG: dict[int, dict[str, int]] = {
    1: {"query_count": 4, "result_limit": 12},
    2: {"query_count": 6, "result_limit": 18},
    3: {"query_count": 8, "result_limit": 24},
}
OPTIONAL_RESOURCE_STATUS_CODES = {403, 404}
SEARCH_CONCURRENCY = 3

STEP_LISTING_INTAKE = "listing_intake"
STEP_QUERY_STRATEGY = "query_strategy"
STEP_COMPETITOR_DISCOVERY = "competitor_discovery"
STEP_COMPETITOR_ENRICHMENT = "competitor_enrichment"
STEP_BENCHMARK_ANALYSIS = "benchmark_analysis"
STEP_OPPORTUNITIES = "opportunities"
STEP_STRATEGY_SYNTHESIS = "strategy_synthesis"
STEP_COPYWRITER = "copywriter_enhancement"

SPANISH_STOPWORDS = {
    "a",
    "al",
    "con",
    "de",
    "del",
    "el",
    "en",
    "la",
    "las",
    "los",
    "para",
    "por",
    "un",
    "una",
    "y",
}
COMPARABLE_NOISE_TOKENS = {
    "negro",
    "negra",
    "blanco",
    "blanca",
    "azul",
    "rosa",
    "rojo",
    "roja",
    "verde",
    "amarillo",
    "aesthetic",
    "vppfull",
    "true",
    "false",
    "nuevo",
}
COMPETITOR_TITLE_NOISE = {
    "ingresa",
    "ingresá",
    "mercado libre",
    "lobato store",
    "store",
}
INDIRECT_COMPETITOR_TOKENS = {
    "mochila",
    "bolso",
    "neceser",
    "portacosmeticos",
    "portacosmetico",
    "cosmetiquera",
    "billetera",
    "cartera",
}


class ListingNormalizationOutput(BaseModel):
    canonical_name: str = ""
    product_type: str = ""
    brand: str | None = None
    dominant_naming_terms: list[str] = Field(default_factory=list)
    key_attributes: list[str] = Field(default_factory=list)
    commercial_variants: list[str] = Field(default_factory=list)
    segment_hint: str = ""


class QueryStrategyOutput(BaseModel):
    search_queries: list[str] = Field(default_factory=list)
    naming_patterns: list[str] = Field(default_factory=list)
    dominant_market_terms: list[str] = Field(default_factory=list)


class ExecutiveSummaryOutput(BaseModel):
    executive_summary: str = ""
    detailed_diagnosis: list[str] = Field(default_factory=list)


class PositioningOutput(BaseModel):
    positioning_strategy: str = ""
    diagnosis_bullets: list[str] = Field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def _tokenize(value: str | None) -> list[str]:
    normalized = _normalize_text(value)
    normalized = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", normalized)
    tokens = re.findall(r"[a-z0-9]+", normalized)
    return [token for token in tokens if len(token) > 1 and token not in SPANISH_STOPWORDS]


def _unique_preserve(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(cleaned)
    return ordered


def _shorten(value: str | None, max_length: int = 120) -> str:
    collapsed = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(collapsed) <= max_length:
        return collapsed
    return f"{collapsed[: max(0, max_length - 3)].rstrip()}..."


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _contains_all_tokens(text_tokens: Sequence[str], candidate_text: str | None) -> bool:
    candidate_tokens = _tokenize(candidate_text)
    if not candidate_tokens:
        return False
    text_token_set = set(text_tokens)
    return all(token in text_token_set for token in candidate_tokens)


def _clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return round(max(minimum, min(maximum, value)), 2)


def _weighted_score(components: Sequence[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in components) or 1.0
    weighted_total = sum(score * weight for score, weight in components)
    return _clamp(weighted_total / total_weight)


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = ratio * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    weight = index - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def _average(values: Iterable[float]) -> float | None:
    cleaned = [float(value) for value in values]
    if not cleaned:
        return None
    return round(sum(cleaned) / len(cleaned), 2)


def _benchmark_confidence(
    *,
    competitor_count: int,
    detailed_count: int,
    priced_count: int,
) -> str:
    if competitor_count >= 6 and detailed_count >= 4 and priced_count >= 4:
        return "high"
    if competitor_count >= 4 and detailed_count >= 2 and priced_count >= 2:
        return "medium"
    return "low"


def _price_benchmark_confidence(*, competitor_count: int, priced_count: int) -> str:
    if competitor_count >= 6 and priced_count >= 4:
        return "high"
    if competitor_count >= 4 and priced_count >= 2:
        return "medium"
    return "low"


def _title_length_score(title: str) -> float:
    length = len((title or "").strip())
    if 45 <= length <= 70:
        return 100.0
    if 35 <= length <= 80:
        return 82.0
    if 25 <= length <= 90:
        return 64.0
    return 38.0


def _keyword_balance_score(tokens: list[str]) -> float:
    if not tokens:
        return 25.0
    unique_ratio = len(set(tokens)) / len(tokens)
    if unique_ratio >= 0.85:
        return 95.0
    if unique_ratio >= 0.72:
        return 78.0
    if unique_ratio >= 0.6:
        return 62.0
    return 38.0


def _brand_from_attributes(attributes: Sequence[dict[str, Any]]) -> str | None:
    for attribute in attributes:
        attr_id = _normalize_text(attribute.get("id"))
        attr_name = _normalize_text(attribute.get("name"))
        if attr_id in {"brand", "marca"} or attr_name == "marca":
            value = attribute.get("value_name") or attribute.get("value") or attribute.get("value_id")
            if value:
                return str(value).strip()
    return None


def _attribute_lookup(attributes: Sequence[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for attribute in attributes:
        raw_value = attribute.get("value_name") or attribute.get("value") or attribute.get("value_id")
        if not raw_value:
            continue
        value = str(raw_value).strip()
        for key in (attribute.get("id"), attribute.get("name")):
            normalized = _normalize_text(str(key or ""))
            if normalized:
                lookup[normalized] = value
    return lookup


def _flatten_attribute_terms(attributes: Sequence[dict[str, Any]], *, limit: int = 8) -> list[str]:
    terms: list[str] = []
    for attribute in attributes:
        name = str(attribute.get("name") or "").strip()
        value = str(attribute.get("value_name") or attribute.get("value") or "").strip()
        if name and value:
            terms.append(f"{name}: {value}")
        elif name:
            terms.append(name)
        if len(terms) >= limit:
            break
    return terms[:limit]


def _extract_required_attributes(category_attributes: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    required: list[dict[str, str]] = []
    for attribute in category_attributes:
        tags = attribute.get("tags") if isinstance(attribute.get("tags"), dict) else {}
        if not isinstance(tags, dict):
            tags = {}
        if not any(
            bool(tags.get(flag))
            for flag in ("required", "catalog_required", "conditional_required")
        ):
            continue
        required.append(
            {
                "id": str(attribute.get("id") or ""),
                "name": str(attribute.get("name") or attribute.get("id") or "").strip(),
            }
        )
    return required


def _extract_common_attribute_names(competitors: Sequence[dict[str, Any]], *, threshold: float = 0.4) -> list[str]:
    counter: Counter[str] = Counter()
    total = len(competitors) or 1
    for competitor in competitors:
        seen: set[str] = set()
        for attribute in competitor.get("attributes", []):
            if not isinstance(attribute, dict):
                continue
            name = str(attribute.get("name") or attribute.get("id") or "").strip()
            normalized = _normalize_text(name)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            counter[name] += 1
    minimum_hits = max(1, math.ceil(total * threshold))
    return [name for name, count in counter.most_common() if count >= minimum_hits][:12]


def _title_overlap_ratio(base_tokens: Sequence[str], candidate_tokens: Sequence[str]) -> float:
    base_set = set(base_tokens)
    candidate_set = set(candidate_tokens)
    if not base_set or not candidate_set:
        return 0.0
    intersection = len(base_set.intersection(candidate_set))
    return intersection / max(len(base_set), len(candidate_set))


def _price_closeness_ratio(base_price: float | None, candidate_price: float | None) -> float:
    if base_price in (None, 0) or candidate_price is None:
        return 0.5
    delta = abs(float(base_price) - float(candidate_price)) / max(float(base_price), 1.0)
    return max(0.0, 1.0 - min(1.0, delta))


def _brand_match_ratio(listing_brand: str | None, candidate_brand: str | None, title_tokens: Sequence[str]) -> float:
    if listing_brand and candidate_brand:
        return 1.0 if _normalize_text(listing_brand) == _normalize_text(candidate_brand) else 0.0
    if listing_brand:
        listing_brand_token = _normalize_text(listing_brand)
        return 1.0 if listing_brand_token and listing_brand_token in title_tokens else 0.0
    return 0.5


def _attribute_overlap_ratio(listing_signal_attributes: Sequence[str], candidate_attribute_lookup: dict[str, str]) -> float:
    normalized_attrs = [_normalize_text(value) for value in listing_signal_attributes if value]
    normalized_attrs = [value for value in normalized_attrs if value]
    if not normalized_attrs:
        return 0.5
    candidate_keys = set(candidate_attribute_lookup.keys())
    hits = sum(1 for value in normalized_attrs if value in candidate_keys)
    return hits / len(normalized_attrs)


def _listing_type_proxy_score(listing_type_id: str | None) -> float:
    proxy = {
        "gold_pro": 95.0,
        "gold_premium": 90.0,
        "gold_special": 85.0,
        "gold": 72.0,
        "silver": 58.0,
        "bronze": 40.0,
        "free": 20.0,
    }
    return proxy.get(str(listing_type_id or "").strip(), 55.0)


def _exposure_priority_score(listing_exposure: str | None, exposure_priority: int | None) -> float:
    if exposure_priority is not None:
        return _clamp(100.0 - (float(exposure_priority) * 20.0))
    normalized = _normalize_text(listing_exposure)
    mapping = {
        "highest": 100.0,
        "high": 80.0,
        "mid": 60.0,
        "low": 40.0,
        "lowest": 20.0,
    }
    return mapping.get(normalized, 55.0)


def _price_band_label(own_price: float | None, *, p25: float | None, p75: float | None, median_price: float | None) -> str:
    if own_price is None or median_price is None:
        return "No se pudo ubicar el precio propio por falta de benchmark suficiente."
    if p25 is not None and own_price < p25:
        return "Tu precio esta por debajo del rango central del mercado."
    if p75 is not None and own_price > p75:
        return "Tu precio esta por encima del rango central del mercado."
    if own_price > median_price:
        return "Tu precio esta apenas por arriba de la mediana del mercado."
    if own_price < median_price:
        return "Tu precio esta apenas por debajo de la mediana del mercado."
    return "Tu precio esta alineado con la mediana del mercado."


def _resource_label(key: str) -> str:
    labels = {
        "category": "la categoria del listing",
        "category_attributes": "los atributos de categoria",
        "technical_specs": "las fichas tecnicas de categoria",
        "listing_type_detail": "el detalle del listing type",
        "listing_health": "el recurso de health del listing",
        "health_actions": "las acciones de health del listing",
    }
    return labels.get(key, key.replace("_", " "))


def _describe_exception(exc: Exception) -> str:
    if isinstance(exc, AppError):
        parts: list[str] = []
        if exc.status_code:
            parts.append(str(exc.status_code))
        message = _shorten(str(exc.message or "").strip(), 140)
        if message:
            parts.append(message)
        if exc.code and exc.code not in {"app_error", "mercadolibre_api_error"}:
            parts.append(str(exc.code))
        return " | ".join(parts) or exc.__class__.__name__
    return _shorten(str(exc).strip() or exc.__class__.__name__, 140)


def _is_optional_resource_unavailable(exc: Exception) -> bool:
    return isinstance(exc, MercadoLibreAPIError) and exc.status_code in OPTIONAL_RESOURCE_STATUS_CODES


def _sanitize_search_query(query: str, *, max_terms: int = 10, max_length: int = 90) -> str:
    collapsed = re.sub(r"\s+", " ", str(query or "")).strip(" ,;:-")
    if not collapsed:
        return ""
    tokens = re.findall(r"[0-9A-Za-zÀ-ÿ][0-9A-Za-zÀ-ÿ./+-]*", collapsed)
    cleaned = " ".join(tokens[:max_terms]) if tokens else collapsed
    return _shorten(cleaned, max_length)


def _query_is_too_literal(query: str, listing_title: str | None) -> bool:
    normalized_query = _normalize_text(query)
    normalized_title = _normalize_text(listing_title)
    if not normalized_query or not normalized_title:
        return False
    if normalized_query == normalized_title:
        return True
    query_tokens = _tokenize(query)
    title_tokens = _tokenize(listing_title)
    if not query_tokens or not title_tokens:
        return False
    return _title_overlap_ratio(query_tokens, title_tokens) >= 0.92 and len(query_tokens) >= max(4, len(title_tokens) - 1)


def _is_probable_item_id(value: str | None) -> bool:
    normalized = str(value or "").strip().upper()
    return bool(re.fullmatch(r"[A-Z]{3}\d{9,13}", normalized))


def _is_marketplace_noise_title(title: str | None) -> bool:
    normalized = _normalize_text(title).replace("-", " ").strip()
    if not normalized:
        return True
    if normalized in COMPETITOR_TITLE_NOISE:
        return True
    tokens = _tokenize(title)
    if len(tokens) < 2:
        return True
    return False


def _permalink_is_noise(permalink: str | None) -> bool:
    lowered = str(permalink or "").lower()
    return any(fragment in lowered for fragment in ("/jms/", "/login", "/nav-header", "/official-store/", "/tienda/"))


def _segment_penalty(title: str | None, product_type: str | None) -> float:
    title_tokens = set(_tokenize(title))
    product_tokens = set(_tokenize(product_type))
    if not title_tokens:
        return 28.0
    if product_tokens and title_tokens.intersection(product_tokens):
        overlap_penalty = 0.0
    else:
        overlap_penalty = 18.0
    indirect_hits = len(title_tokens.intersection(INDIRECT_COMPETITOR_TOKENS))
    if indirect_hits and product_tokens.intersection(title_tokens):
        return overlap_penalty + 8.0
    if indirect_hits:
        return overlap_penalty + 18.0
    return overlap_penalty


async def _mark_progress(state: ListingDoctorState, step_key: str, status: str, message: str | None = None) -> None:
    hook = state.get("progress_hook")
    if hook is None:
        return
    await hook(step_key, status, message)


async def _trace_event(
    state: ListingDoctorState | dict[str, Any] | None,
    *,
    agent: str,
    node: str,
    phase: str,
    message: str,
    details: Any | None = None,
) -> None:
    if not isinstance(state, dict):
        return
    hook = state.get("trace_hook")
    if hook is None:
        return
    await hook(agent, node, phase, message, details)


def _append_warning(existing: Sequence[str], *messages: str) -> list[str]:
    return _unique_preserve([*existing, *messages])


def _append_evidence(existing: Sequence[str], *messages: str) -> list[str]:
    return _unique_preserve([*existing, *messages])


def _top_keywords(titles: Sequence[str], *, limit: int = 8) -> list[str]:
    counter: Counter[str] = Counter()
    for title in titles:
        counter.update(_tokenize(title))
    return [term for term, _ in counter.most_common(limit)]


def _top_brands(brands: Sequence[str], *, limit: int = 6) -> list[str]:
    counter = Counter(_normalize_text(brand) for brand in brands if brand)
    ordered = [brand for brand, _ in counter.most_common(limit) if brand]
    return [brand.title() for brand in ordered]


def _descriptor_terms(
    product_type: str | None,
    dominant_terms: Sequence[str],
    attribute_values: Sequence[str],
    brand: str | None,
    *,
    limit: int = 5,
) -> list[str]:
    product_tokens = set(_tokenize(product_type))
    brand_tokens = set(_tokenize(brand))
    descriptors: list[str] = []
    for source in [dominant_terms, attribute_values]:
        for raw_value in source:
            cleaned = str(raw_value or "").strip()
            if not cleaned:
                continue
            tokens = _tokenize(cleaned)
            if not tokens:
                continue
            joined = " ".join(
                token for token in tokens if token not in product_tokens and token not in brand_tokens
            ).strip()
            if (
                not joined
                or joined in COMPARABLE_NOISE_TOKENS
                or any(token in COMPARABLE_NOISE_TOKENS for token in joined.split())
            ):
                continue
            descriptors.append(joined)
    return _unique_preserve(descriptors)[:limit]


def _is_near_identical_competitor(
    *,
    listing_title: str | None,
    candidate_title: str | None,
    listing_brand: str | None,
    candidate_brand: str | None,
    listing_price: float | None,
    candidate_price: float | None,
) -> bool:
    base_tokens = _tokenize(listing_title)
    candidate_tokens = _tokenize(candidate_title)
    if not base_tokens or not candidate_tokens:
        return False
    title_overlap = _title_overlap_ratio(base_tokens, candidate_tokens)
    exact_title = _normalize_text(listing_title) == _normalize_text(candidate_title)
    brand_match = _brand_match_ratio(listing_brand, candidate_brand, candidate_tokens) >= 0.95
    price_match = _price_closeness_ratio(listing_price, candidate_price) >= 0.88
    return exact_title or (title_overlap >= 0.9) or (title_overlap >= 0.82 and brand_match and price_match)


async def _invoke_structured(
    llm: Any,
    schema: type[BaseModel],
    *,
    system_prompt: str,
    human_payload: dict[str, Any],
    trace_state: ListingDoctorState | None = None,
    trace_agent: str | None = None,
    trace_node: str | None = None,
) -> BaseModel | None:
    if llm is None:
        await _trace_event(
            trace_state,
            agent=trace_agent or "llm",
            node=trace_node or "structured_call",
            phase="info",
            message="LLM no disponible; se usara fallback deterministico.",
            details={"schema": schema.__name__},
        )
        return None
    try:
        await _trace_event(
            trace_state,
            agent=trace_agent or "llm",
            node=trace_node or "structured_call",
            phase="info",
            message="Invocando LLM con salida estructurada.",
            details={
                "schema": schema.__name__,
                "system_prompt": system_prompt,
                "human_payload": human_payload,
            },
        )
        structured = llm.with_structured_output(schema)
        response = await structured.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=json.dumps(human_payload, ensure_ascii=False)),
            ]
        )
        parsed = response if isinstance(response, schema) else schema.model_validate(response)
        await _trace_event(
            trace_state,
            agent=trace_agent or "llm",
            node=trace_node or "structured_call",
            phase="info",
            message="LLM respondio correctamente.",
            details={
                "schema": schema.__name__,
                "output": parsed.model_dump(mode="json"),
            },
        )
        return parsed
    except Exception as exc:
        await _trace_event(
            trace_state,
            agent=trace_agent or "llm",
            node=trace_node or "structured_call",
            phase="failed",
            message="Fallo una llamada LLM estructurada.",
            details={
                "schema": schema.__name__,
                "error": str(exc),
                "exception_type": exc.__class__.__name__,
            },
        )
        return None


def _listing_seed_queries(listing: dict[str, Any], normalized_listing: dict[str, Any], product_signals: dict[str, Any]) -> list[str]:
    brand = str(product_signals.get("brand") or normalized_listing.get("brand") or "").strip()
    product_type = str(product_signals.get("product_type") or normalized_listing.get("product_type") or "").strip()
    category_name = str(listing.get("category_name") or "").strip()
    dominant_terms = [str(value).strip() for value in normalized_listing.get("dominant_naming_terms", []) if value]
    attr_values = [str(value).strip() for value in product_signals.get("attribute_values", []) if value]
    descriptors = _descriptor_terms(product_type, dominant_terms, attr_values, brand, limit=5)

    seeds: list[str] = []
    if product_type:
        seeds.append(product_type)
    if product_type and descriptors:
        seeds.append(f"{product_type} {descriptors[0]}")
    if product_type and len(descriptors) >= 2:
        seeds.append(f"{product_type} {descriptors[0]} {descriptors[1]}")
    if category_name and category_name != product_type:
        seeds.append(category_name)
    if category_name and descriptors:
        seeds.append(f"{category_name} {descriptors[0]}")
    if brand and product_type and descriptors:
        seeds.append(f"{brand} {product_type} {descriptors[0]}")
    elif brand and product_type:
        seeds.append(f"{brand} {product_type}")
    seeds.extend(descriptors[:3])
    return _unique_preserve(seeds)


def _fallback_listing_normalization(listing: dict[str, Any]) -> dict[str, Any]:
    title = str(listing.get("title") or "").strip()
    title_tokens = _tokenize(title)
    brand = listing.get("brand")
    product_type = str(listing.get("category_name") or "").strip() or "Producto"
    dominant_naming_terms = title_tokens[:6]
    key_attributes = [term for term in listing.get("key_attributes", []) if term][:6]
    return {
        "canonical_name": title,
        "product_type": product_type,
        "brand": brand,
        "dominant_naming_terms": dominant_naming_terms,
        "key_attributes": key_attributes,
        "commercial_variants": dominant_naming_terms[1:4],
        "segment_hint": "",
    }


def _fallback_query_expansion(seed_queries: Sequence[str], trend_keywords: Sequence[str], normalized_listing: dict[str, Any]) -> dict[str, Any]:
    product_type = str(normalized_listing.get("product_type") or "").strip()
    brand = str(normalized_listing.get("brand") or "").strip()
    dominant_terms = [str(term).strip() for term in normalized_listing.get("dominant_naming_terms", []) if term]
    descriptors = _descriptor_terms(product_type, dominant_terms, normalized_listing.get("key_attributes", []), brand, limit=4)
    queries = list(seed_queries)
    if product_type and descriptors:
        queries.append(f"{product_type} {descriptors[0]}")
    if product_type and len(descriptors) >= 2:
        queries.append(f"{product_type} {descriptors[0]} {descriptors[1]}")
    if brand and product_type and descriptors:
        queries.append(f"{brand} {product_type} {descriptors[0]}")
    queries.extend(trend_keywords[:3])
    return {
        "search_queries": _unique_preserve(queries),
        "naming_patterns": descriptors[:4] or dominant_terms[:4],
        "dominant_market_terms": _unique_preserve([*dominant_terms[:6], *descriptors[:4]])[:6],
    }


def _fallback_executive_summary(scores: dict[str, float], findings: dict[str, Any], market_summary: dict[str, Any]) -> str:
    strongest = findings.get("strengths", [])[:2]
    weakest = findings.get("weaknesses", [])[:2]
    median_price = market_summary.get("median_price")
    price_confidence = str(market_summary.get("price_benchmark_confidence") or "low")
    benchmark_confidence = str(market_summary.get("benchmark_confidence") or "low")
    price_note = (
        f"La mediana del benchmark es {median_price:.2f}."
        if isinstance(median_price, (int, float)) and price_confidence != "low"
        else "El benchmark de precio fue limitado y no conviene usarlo para conclusiones duras."
    )
    return (
        f"El listing obtiene {scores.get('overall', 0):.1f}/100. "
        f"Sus mejores senales estan en {', '.join(strongest) if strongest else 'algunos fundamentos del listing'}. "
        f"Los principales gaps aparecen en {', '.join(weakest) if weakest else 'la distancia contra el benchmark'}. "
        f"Confianza general del benchmark: {benchmark_confidence}. {price_note}"
    )


def _fallback_detailed_diagnosis(listing: dict[str, Any], findings: dict[str, Any], actions: Sequence[dict[str, Any]]) -> list[str]:
    bullets: list[str] = []
    if listing.get("health_actions"):
        bullets.append("La publicacion tiene alertas de calidad que conviene resolver antes de optimizar el resto.")
    if findings.get("title_gaps"):
        bullets.append(f"Titulo: {findings['title_gaps'][0]}")
    if findings.get("pricing_position"):
        bullets.append(f"Precio: {findings['pricing_position'][0]}")
    if findings.get("missing_attributes"):
        bullets.append(
            f"Atributos: faltan {min(3, len(findings['missing_attributes']))} atributos importantes frente al benchmark."
        )
    if actions:
        bullets.append(f"Prioridad inmediata: {actions[0].get('summary', actions[0].get('title', ''))}")
    return bullets[:4]


def _fallback_positioning_strategy(scores: dict[str, float], market_summary: dict[str, Any], findings: dict[str, Any]) -> str:
    keywords = ", ".join(market_summary.get("dominant_keywords", [])[:3])
    if str(market_summary.get("price_benchmark_confidence") or "low") == "low":
        return (
            "Conviene priorizar claridad comercial, atributos y conversion del listing antes de tomar decisiones fuertes de precio, "
            f"alineando el naming con terminos como {keywords or 'los patrones dominantes del benchmark'}."
        )
    if scores.get("price", 0) < 60:
        return (
            "Conviene reposicionar la oferta cerca del rango central del mercado y alinear el naming "
            f"con terminos como {keywords or 'los patrones dominantes del benchmark'}."
        )
    return (
        "Conviene sostener el precio y mejorar la conversion del listing reforzando atributos, "
        f"descripcion y naming dominante ({keywords or 'benchmark'})."
    )


def _action_priority_rank(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(priority, 1)


def _action_impact_rank(impact: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(impact, 1)


def _action_effort_rank(effort: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(effort, 1)


def build_load_listing_context_node(
    *,
    items_service: ItemsService,
    market_research: MarketResearchAdapter,
):
    async def load_listing_context_node(state: ListingDoctorState) -> dict[str, Any]:
        await _mark_progress(state, STEP_LISTING_INTAKE, "running", "Cargando publicacion y metadata base")

        account_key = state["account_key"]
        item_id = state["item_id"]

        item_detail, raw_listing = await asyncio.gather(
            items_service.get_item(account_key, item_id),
            market_research.get_owned_item_detail(account_key, item_id),
        )

        site_id = str(raw_listing.get("site_id") or state["site_id"]).strip().upper()
        category_id = str(raw_listing.get("category_id") or item_detail.category_id or "").strip() or None
        listing_type_id = str(raw_listing.get("listing_type_id") or item_detail.listing_type_id or "").strip() or None
        category_name = None
        category_attributes: list[dict[str, Any]] = []
        listing_type_detail: dict[str, Any] = {}
        listing_health: dict[str, Any] = {}
        health_actions: list[dict[str, Any]] = []
        warnings = list(state.get("warnings", []))
        uncertainties = list(state.get("evidence", {}).get("uncertainties", []))

        tasks: list[Any] = []
        task_keys: list[str] = []
        if category_id:
            tasks.extend(
                [
                    market_research.get_category(account_key, category_id),
                    market_research.get_category_attributes(account_key, category_id),
                    market_research.get_category_technical_specs(account_key, category_id),
                ]
            )
            task_keys.extend(["category", "category_attributes", "technical_specs"])
        if listing_type_id:
            tasks.append(
                market_research.get_listing_type_detail(
                    account_key,
                    site_id=site_id,
                    listing_type_id=listing_type_id,
                )
            )
            task_keys.append("listing_type_detail")
        tasks.append(market_research.get_listing_health(account_key, item_id))
        task_keys.append("listing_health")
        tasks.append(market_research.get_listing_health_actions(account_key, item_id))
        task_keys.append("health_actions")

        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        resolved: dict[str, Any] = {}
        for key, result in zip(task_keys, task_results, strict=False):
            if isinstance(result, Exception):
                label = _resource_label(key)
                detail = _describe_exception(result)
                await _trace_event(
                    state,
                    agent="listing_intake_agent",
                    node="load_listing_context.resource",
                    phase="info",
                    message=f"No se pudo enriquecer el recurso {key}.",
                    details={
                        "resource": key,
                        "label": label,
                        "error": detail,
                        "exception_type": result.__class__.__name__,
                        "error_details": result.details if isinstance(result, AppError) else None,
                    },
                )
                if key in {"listing_health", "health_actions"} and _is_optional_resource_unavailable(result):
                    uncertainties = _append_evidence(
                        uncertainties,
                        f"Mercado Libre no expuso {label} para este listing ({detail}); se continuo con metadata base.",
                    )
                    continue
                if key in {"technical_specs", "listing_type_detail"} and isinstance(result, MercadoLibreAPIError) and result.status_code in {401, 403, 404}:
                    uncertainties = _append_evidence(
                        uncertainties,
                        f"No fue posible usar {label} en esta ejecucion ({detail}); se continuo con señales base del listing.",
                    )
                    continue
                warnings = _append_warning(
                    warnings,
                    f"No se pudo enriquecer {label} del listing analizado ({detail}).",
                )
                uncertainties = _append_evidence(
                    uncertainties,
                    f"{label.capitalize()} no estuvo disponible durante el intake.",
                )
                continue
            resolved[key] = result

        category_payload = resolved.get("category")
        if isinstance(category_payload, dict):
            category_name = str(category_payload.get("name") or "").strip() or None

        category_attributes = (
            resolved.get("category_attributes")
            if isinstance(resolved.get("category_attributes"), list)
            else []
        )
        technical_specs = (
            resolved.get("technical_specs")
            if isinstance(resolved.get("technical_specs"), dict)
            else {}
        )
        listing_type_detail = (
            resolved.get("listing_type_detail")
            if isinstance(resolved.get("listing_type_detail"), dict)
            else {}
        )
        listing_health = resolved.get("listing_health") if isinstance(resolved.get("listing_health"), dict) else {}
        health_actions = resolved.get("health_actions") if isinstance(resolved.get("health_actions"), list) else []

        attributes = list(item_detail.attributes or [])
        brand = _brand_from_attributes(attributes)
        description_text = str(item_detail.description or "").strip()
        health_action_names = [
            str(action.get("message") or action.get("name") or action.get("id") or "").strip()
            for action in health_actions
            if isinstance(action, dict)
        ]
        health_action_names = [value for value in health_action_names if value]

        listing_exposure = None
        listing_config = listing_type_detail.get("configuration") if isinstance(listing_type_detail.get("configuration"), dict) else {}
        if listing_config:
            listing_exposure = str(listing_config.get("listing_exposure") or "").strip() or None

        required_attributes = _extract_required_attributes(category_attributes)
        attribute_lookup = _attribute_lookup(attributes)
        missing_required = [
            item["name"]
            for item in required_attributes
            if _normalize_text(item["id"]) not in attribute_lookup and _normalize_text(item["name"]) not in attribute_lookup
        ]

        listing = ListingDoctorListingSummary(
            item_id=item_detail.id,
            title=item_detail.title,
            status=item_detail.status,
            category_id=category_id,
            category_name=category_name,
            site_id=site_id,
            currency_id=item_detail.currency_id,
            price=item_detail.price,
            sold_quantity=item_detail.sold_quantity,
            available_quantity=item_detail.available_quantity,
            condition=item_detail.condition,
            listing_type_id=listing_type_id,
            listing_exposure=listing_exposure,
            health=_safe_float(raw_listing.get("health") or listing_health.get("health") or item_detail.health),
            health_actions=health_action_names[:8],
            brand=brand,
            product_type=None,
            key_attributes=_flatten_attribute_terms(attributes, limit=8),
            missing_attributes=missing_required[:12],
            attributes_count=len(attributes),
            pictures_count=len(item_detail.pictures or []),
            description_present=bool(description_text),
            description_length=len(description_text),
            thumbnail=item_detail.thumbnail,
            permalink=item_detail.permalink,
            last_updated=item_detail.last_updated,
        ).model_dump(mode="json")

        factual_points = [
            f"Se analizo la publicacion {item_detail.id}.",
            f"Categoria: {category_name or category_id or 'sin categoria resoluble'}.",
            f"Precio actual: {item_detail.price if item_detail.price is not None else 'N/D'} {item_detail.currency_id or ''}".strip(),
            f"Atributos cargados: {len(attributes)}.",
            f"Fotos visibles: {len(item_detail.pictures or [])}.",
        ]
        if listing["description_present"]:
            factual_points.append(f"La descripcion actual tiene {listing['description_length']} caracteres.")
        else:
            factual_points.append("La publicacion no tiene descripcion utilizable.")
        if health_action_names:
            factual_points.append(f"Se detectaron {len(health_action_names)} alertas o acciones de calidad del listing.")

        raw_listing_payload = dict(raw_listing)
        raw_listing_payload["description"] = description_text
        raw_listing_payload["category_attributes"] = category_attributes
        raw_listing_payload["technical_specs"] = technical_specs
        raw_listing_payload["listing_type_detail"] = listing_type_detail

        evidence = ListingDoctorEvidence(
            factual_points=factual_points,
            proxy_points=list(state.get("evidence", {}).get("proxy_points", [])),
            uncertainties=uncertainties,
        ).model_dump(mode="json")

        return {
            "site_id": site_id,
            "raw_listing": raw_listing_payload,
            "listing": listing,
            "warnings": warnings,
            "evidence": evidence,
        }

    return load_listing_context_node


def build_normalize_listing_node(*, llm: Any):
    async def normalize_listing_node(state: ListingDoctorState) -> dict[str, Any]:
        listing = dict(state.get("listing", {}))
        raw_listing = dict(state.get("raw_listing", {}))
        human_payload = {
            "title": listing.get("title"),
            "category_name": listing.get("category_name"),
            "brand": listing.get("brand"),
            "attributes": listing.get("key_attributes", []),
            "description_excerpt": str(raw_listing.get("description") or "")[:1200],
        }
        llm_output = await _invoke_structured(
            llm,
            ListingNormalizationOutput,
            system_prompt=LISTING_NORMALIZER_PROMPT,
            human_payload=human_payload,
            trace_state=state,
            trace_agent="listing_intake_agent",
            trace_node="normalize_listing.llm",
        )
        normalized_listing = (
            llm_output.model_dump(mode="json")
            if llm_output is not None
            else _fallback_listing_normalization(listing)
        )
        if not normalized_listing.get("brand") and listing.get("brand"):
            normalized_listing["brand"] = listing.get("brand")
        if not normalized_listing.get("product_type"):
            normalized_listing["product_type"] = listing.get("category_name") or "Producto"
        listing["brand"] = normalized_listing.get("brand") or listing.get("brand")
        listing["product_type"] = normalized_listing.get("product_type") or listing.get("product_type")
        return {
            "listing": listing,
            "normalized_listing": normalized_listing,
        }

    return normalize_listing_node


def build_extract_product_signals_node():
    async def extract_product_signals_node(state: ListingDoctorState) -> dict[str, Any]:
        raw_listing = dict(state.get("raw_listing", {}))
        listing = dict(state.get("listing", {}))
        normalized_listing = dict(state.get("normalized_listing", {}))
        attributes = raw_listing.get("attributes") if isinstance(raw_listing.get("attributes"), list) else []
        category_attributes = (
            raw_listing.get("category_attributes")
            if isinstance(raw_listing.get("category_attributes"), list)
            else []
        )
        attribute_lookup = _attribute_lookup(attributes)
        required_attributes = _extract_required_attributes(category_attributes)
        required_names = [item["name"] for item in required_attributes]
        present_required_names = [
            item["name"]
            for item in required_attributes
            if _normalize_text(item["id"]) in attribute_lookup or _normalize_text(item["name"]) in attribute_lookup
        ]
        attribute_values = [
            value
            for _, value in list(attribute_lookup.items())[:8]
            if value
        ]
        product_signals = {
            "brand": normalized_listing.get("brand") or listing.get("brand"),
            "product_type": normalized_listing.get("product_type") or listing.get("category_name"),
            "title_tokens": _tokenize(listing.get("title")),
            "dominant_terms": normalized_listing.get("dominant_naming_terms", []),
            "key_attribute_names": [str(term).split(":", 1)[0].strip() for term in listing.get("key_attributes", [])],
            "attribute_values": attribute_values[:6],
            "required_attribute_names": required_names,
            "present_required_attribute_names": present_required_names,
            "description_text": str(raw_listing.get("description") or "").strip(),
            "seller_id": raw_listing.get("seller_id"),
        }
        listing["missing_attributes"] = [
            name for name in required_names if name not in present_required_names
        ][:12]
        await _mark_progress(state, STEP_LISTING_INTAKE, "completed", "Listing intake listo")
        return {
            "listing": listing,
            "product_signals": product_signals,
        }

    return extract_product_signals_node


def build_seed_queries_node():
    async def build_seed_queries_node(state: ListingDoctorState) -> dict[str, Any]:
        await _mark_progress(state, STEP_QUERY_STRATEGY, "running", "Construyendo queries semilla")
        listing = dict(state.get("listing", {}))
        normalized_listing = dict(state.get("normalized_listing", {}))
        product_signals = dict(state.get("product_signals", {}))
        query_bundle = {
            "seed_queries": _listing_seed_queries(listing, normalized_listing, product_signals),
            "trend_keywords": [],
            "search_queries": [],
            "naming_patterns": [],
            "dominant_market_terms": list(normalized_listing.get("dominant_naming_terms", [])),
        }
        return {"query_bundle": query_bundle}

    return build_seed_queries_node


def build_expand_market_queries_node(
    *,
    llm: Any,
    market_research: MarketResearchAdapter,
):
    async def expand_market_queries_node(state: ListingDoctorState) -> dict[str, Any]:
        account_key = state["account_key"]
        site_id = state["site_id"]
        listing = dict(state.get("listing", {}))
        query_bundle = dict(state.get("query_bundle", {}))
        warnings = list(state.get("warnings", []))
        evidence = dict(state.get("evidence", {}))
        uncertainties = list(evidence.get("uncertainties", []))

        trend_keywords: list[str] = []
        try:
            trends = await market_research.get_trends(
                account_key,
                site_id=site_id,
                category_id=listing.get("category_id"),
            )
            trend_keywords = [
                str(entry.get("keyword") or entry.get("query") or "").strip()
                for entry in trends
                if isinstance(entry, dict)
            ]
            trend_keywords = [term for term in trend_keywords if term][:6]
        except Exception as exc:
            await _trace_event(
                state,
                agent="query_strategy_agent",
                node="expand_market_queries.trends",
                phase="info",
                message="No se pudieron enriquecer tendencias para expansion de queries.",
                details={
                    "site_id": site_id,
                    "category_id": listing.get("category_id"),
                    "error": _describe_exception(exc),
                    "exception_type": exc.__class__.__name__,
                    "error_details": exc.details if isinstance(exc, AppError) else None,
                },
            )
            uncertainties = _append_evidence(
                uncertainties,
                f"No se pudieron usar tendencias del sitio para expandir queries ({_describe_exception(exc)}).",
            )

        query_bundle["trend_keywords"] = trend_keywords

        llm_output = await _invoke_structured(
            llm,
            QueryStrategyOutput,
            system_prompt=QUERY_STRATEGIST_PROMPT,
            human_payload={
                "listing": listing,
                "normalized_listing": state.get("normalized_listing", {}),
                "seed_queries": query_bundle.get("seed_queries", []),
                "trend_keywords": trend_keywords,
            },
            trace_state=state,
            trace_agent="query_strategy_agent",
            trace_node="expand_market_queries.llm",
        )

        expanded = (
            llm_output.model_dump(mode="json")
            if llm_output is not None
            else _fallback_query_expansion(
                query_bundle.get("seed_queries", []),
                trend_keywords,
                dict(state.get("normalized_listing", {})),
            )
        )
        query_bundle["search_queries"] = expanded.get("search_queries", [])
        query_bundle["naming_patterns"] = expanded.get("naming_patterns", [])
        query_bundle["dominant_market_terms"] = expanded.get("dominant_market_terms", [])
        return {
            "query_bundle": query_bundle,
            "warnings": warnings,
            "evidence": {**evidence, "uncertainties": uncertainties},
        }

    return expand_market_queries_node


def build_dedupe_queries_node():
    async def dedupe_queries_node(state: ListingDoctorState) -> dict[str, Any]:
        query_bundle = dict(state.get("query_bundle", {}))
        config = SEARCH_DEPTH_CONFIG.get(int(state.get("search_depth", 2)), SEARCH_DEPTH_CONFIG[2])
        queries = query_bundle.get("search_queries") or query_bundle.get("seed_queries") or []
        listing_title = dict(state.get("listing", {})).get("title")
        cleaned: list[str] = []
        for query in queries:
            collapsed = _sanitize_search_query(str(query or ""))
            if len(collapsed) < 3:
                continue
            if _query_is_too_literal(collapsed, listing_title):
                continue
            cleaned.append(collapsed)
        if not cleaned:
            cleaned = _listing_seed_queries(
                dict(state.get("listing", {})),
                dict(state.get("normalized_listing", {})),
                dict(state.get("product_signals", {})),
            )
        query_bundle["search_queries"] = _unique_preserve(cleaned)[: config["query_count"]]
        await _mark_progress(state, STEP_QUERY_STRATEGY, "completed", "Queries finales listas para competir")
        return {"query_bundle": query_bundle}

    return dedupe_queries_node


def build_search_marketplace_node(*, market_research: MarketResearchAdapter):
    async def search_marketplace_node(state: ListingDoctorState) -> dict[str, Any]:
        await _mark_progress(state, STEP_COMPETITOR_DISCOVERY, "running", "Buscando competencia real en Mercado Libre")
        account_key = state["account_key"]
        site_id = state["site_id"]
        listing = dict(state.get("listing", {}))
        query_bundle = dict(state.get("query_bundle", {}))
        queries = query_bundle.get("search_queries", [])
        config = SEARCH_DEPTH_CONFIG.get(int(state.get("search_depth", 2)), SEARCH_DEPTH_CONFIG[2])
        warnings = list(state.get("warnings", []))
        evidence = dict(state.get("evidence", {}))
        factual_points = list(evidence.get("factual_points", []))
        uncertainties = list(evidence.get("uncertainties", []))
        category_id = listing.get("category_id")
        category_name = str(listing.get("category_name") or "").strip()
        listing_permalink = str(listing.get("permalink") or "").strip()
        semaphore = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def _run_search(query: str) -> dict[str, Any]:
            sanitized_query = _sanitize_search_query(query)
            attempts: list[str] = []
            scopes: list[tuple[str, str | None, str | None]] = []
            if category_id:
                scopes.append(("category", category_id, sanitized_query))
            scopes.append(("site", None, sanitized_query))
            if category_id:
                scopes.append(("category_browse", category_id, None))

            for index, (scope_name, scoped_category, scoped_query) in enumerate(scopes):
                try:
                    payload = await market_research.search_items(
                        account_key,
                        site_id=site_id,
                        query=scoped_query,
                        category_id=scoped_category,
                        limit=config["result_limit"],
                    )
                    items = payload.get("results") if isinstance(payload, dict) else []
                    if items or scope_name in {"site", "category_browse"} or len(scopes) == 1:
                        result = {
                            "query": sanitized_query,
                            "total_results": payload.get("paging", {}).get("total") if isinstance(payload, dict) else None,
                            "items": items,
                            "search_scope": scope_name,
                            "fallback_used": index > 0,
                            "succeeded": True,
                            "errors": attempts,
                        }
                        await _trace_event(
                            state,
                            agent="competitor_discovery_agent",
                            node="search_marketplace.query",
                            phase="info",
                            message=f"Query competitiva resuelta: {sanitized_query}",
                            details=result,
                        )
                        return result
                except Exception as exc:
                    attempts.append(_describe_exception(exc))

            try:
                payload = await market_research.search_items_via_web_listing(
                    site_id=site_id,
                    query=sanitized_query,
                    limit=config["result_limit"],
                )
                items = payload.get("results") if isinstance(payload, dict) else []
                if items:
                    result = {
                        "query": sanitized_query,
                        "total_results": payload.get("paging", {}).get("total") if isinstance(payload, dict) else None,
                        "items": items,
                        "search_scope": "web_listing",
                        "fallback_used": True,
                        "succeeded": True,
                        "errors": attempts,
                        "source_method": payload.get("source_method"),
                        "source_url": payload.get("source_url"),
                    }
                    await _trace_event(
                        state,
                        agent="competitor_discovery_agent",
                        node="search_marketplace.query",
                        phase="info",
                        message=f"Query competitiva resuelta por listado web: {sanitized_query}",
                        details=result,
                    )
                    return result
            except Exception as exc:
                attempts.append(_describe_exception(exc))

            result = {
                "query": sanitized_query,
                "total_results": None,
                "items": [],
                "search_scope": "failed",
                "fallback_used": bool(category_id),
                "succeeded": False,
                "errors": attempts,
            }
            await _trace_event(
                state,
                agent="competitor_discovery_agent",
                node="search_marketplace.query",
                phase="failed",
                message=f"Query competitiva fallida: {sanitized_query}",
                details=result,
            )
            return result

        async def _guarded_run(query: str) -> dict[str, Any]:
            async with semaphore:
                return await _run_search(query)

        tasks = [_guarded_run(query) for query in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        search_runs: list[dict[str, Any]] = []
        failed_queries: list[str] = []
        fallback_queries = 0
        for result in results:
            if isinstance(result, Exception):
                failed_queries.append(_describe_exception(result))
                continue
            if not result.get("succeeded"):
                errors = result.get("errors") if isinstance(result.get("errors"), list) else []
                failed_queries.append(
                    f"{result.get('query') or 'query'}: {errors[0] if errors else 'sin detalle adicional'}"
                )
                continue
            if result.get("fallback_used"):
                fallback_queries += 1
            search_runs.append(result)

        if not search_runs and category_name:
            try:
                payload = await market_research.browse_category_public(
                    site_id=site_id,
                    category_name=category_name,
                    limit=config["result_limit"],
                )
                category_items = payload.get("results") if isinstance(payload, dict) else []
                if category_items:
                    category_run = {
                        "query": category_name,
                        "total_results": payload.get("paging", {}).get("total") if isinstance(payload, dict) else None,
                        "items": category_items,
                        "search_scope": "web_category_listing",
                        "fallback_used": True,
                        "succeeded": True,
                        "errors": [],
                        "source_method": payload.get("source_method"),
                        "source_url": payload.get("source_url"),
                    }
                    search_runs.append(category_run)
                    await _trace_event(
                        state,
                        agent="competitor_discovery_agent",
                        node="search_marketplace.category_web",
                        phase="info",
                        message="Se recuperaron candidatos desde el listado publico de categoria.",
                        details=category_run,
                    )
            except Exception as exc:
                uncertainties = _append_evidence(
                    uncertainties,
                    f"El fallback de listado web por categoria no estuvo disponible ({_describe_exception(exc)}).",
                )
                await _trace_event(
                    state,
                    agent="competitor_discovery_agent",
                    node="search_marketplace.category_web",
                    phase="failed",
                    message="Fallo el fallback de listado web por categoria.",
                    details={
                        "category_name": category_name,
                        "error": _describe_exception(exc),
                        "exception_type": exc.__class__.__name__,
                        "error_details": exc.details if isinstance(exc, AppError) else None,
                    },
                )

        if (not search_runs or sum(len(run.get("items", [])) for run in search_runs) < 6) and listing_permalink:
            try:
                payload = await market_research.extract_related_items_from_public_page(
                    site_id=site_id,
                    permalink=listing_permalink,
                    limit=max(config["result_limit"], 18),
                )
                related_items = payload.get("results") if isinstance(payload, dict) else []
                if related_items:
                    related_run = {
                        "query": "related_from_item_page",
                        "total_results": payload.get("paging", {}).get("total") if isinstance(payload, dict) else None,
                        "items": related_items,
                        "search_scope": "public_item_page",
                        "fallback_used": True,
                        "succeeded": True,
                        "errors": [],
                        "source_method": payload.get("source_method"),
                        "source_url": payload.get("source_url"),
                    }
                    search_runs.append(related_run)
                    await _trace_event(
                        state,
                        agent="competitor_discovery_agent",
                        node="search_marketplace.related_page",
                        phase="info",
                        message="Se recuperaron candidatos desde la pagina publica del item.",
                        details=related_run,
                    )
            except Exception as exc:
                uncertainties = _append_evidence(
                    uncertainties,
                    f"No se pudieron usar recomendaciones o links del item publico como fuente alternativa ({_describe_exception(exc)}).",
                )
                await _trace_event(
                    state,
                    agent="competitor_discovery_agent",
                    node="search_marketplace.related_page",
                    phase="failed",
                    message="Fallo el fallback desde la pagina publica del item.",
                    details={
                        "permalink": listing_permalink,
                        "error": _describe_exception(exc),
                        "exception_type": exc.__class__.__name__,
                        "error_details": exc.details if isinstance(exc, AppError) else None,
                    },
                )

        if queries:
            factual_points = _append_evidence(
                factual_points,
                f"Se intentaron {len(queries)} queries de research competitivo.",
            )
        if search_runs:
            used_sources = _unique_preserve(
                [
                    str(run.get("search_scope") or run.get("source_method") or "")
                    for run in search_runs
                    if run.get("search_scope") or run.get("source_method")
                ]
            )
            factual_points = _append_evidence(
                factual_points,
                f"Fuentes competitivas usadas: {', '.join(used_sources)}.",
            )
        if fallback_queries:
            uncertainties = _append_evidence(
                uncertainties,
                f"{fallback_queries} queries necesitaron fallback sin categoria para recuperar comparables.",
            )
        if failed_queries:
            for failure in failed_queries[:2]:
                warnings = _append_warning(
                    warnings,
                    f"Se omitio una query de competencia ({_shorten(failure, 170)}).",
                )
            if len(failed_queries) > 2:
                warnings = _append_warning(
                    warnings,
                    f"Otras {len(failed_queries) - 2} queries de competencia tambien fallaron y se omitieron.",
                )
        if not search_runs:
            warnings = _append_warning(
                warnings,
                "No se pudieron recuperar resultados de competencia tras reintentos con y sin categoria.",
            )
            uncertainties = _append_evidence(
                uncertainties,
                "La capa de search no devolvio payloads competitivos utilizables en esta ejecucion.",
            )
        evidence["factual_points"] = factual_points
        evidence["uncertainties"] = uncertainties
        return {"search_runs": search_runs, "warnings": warnings, "evidence": evidence}

    return search_marketplace_node


def build_collect_candidates_node():
    async def collect_candidates_node(state: ListingDoctorState) -> dict[str, Any]:
        listing = dict(state.get("listing", {}))
        search_runs = list(state.get("search_runs", []))
        own_item_id = str(listing.get("item_id") or "")
        own_seller_id = state.get("product_signals", {}).get("seller_id")
        product_type = str(state.get("product_signals", {}).get("product_type") or listing.get("category_name") or "").strip()

        candidate_map: dict[str, dict[str, Any]] = {}
        for run in search_runs:
            query = str(run.get("query") or "")
            items = run.get("items") if isinstance(run.get("items"), list) else []
            for index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "").strip()
                if not item_id or item_id == own_item_id:
                    continue
                if not _is_probable_item_id(item_id):
                    continue
                title = str(item.get("title") or "").strip()
                permalink = item.get("permalink")
                if _is_marketplace_noise_title(title) or _permalink_is_noise(permalink):
                    continue
                seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}
                seller_id = seller.get("id")
                if own_seller_id and seller_id and str(own_seller_id) == str(seller_id):
                    continue
                current = candidate_map.setdefault(
                    item_id,
                    {
                        "item_id": item_id,
                        "title": title,
                        "price": _safe_float(item.get("price")),
                        "currency_id": item.get("currency_id"),
                        "sold_quantity": _safe_int(item.get("sold_quantity")),
                        "status": item.get("status"),
                        "brand": _brand_from_attributes(item.get("attributes", []))
                        if isinstance(item.get("attributes"), list)
                        else None,
                        "condition": item.get("condition"),
                        "listing_type_id": item.get("listing_type_id"),
                        "thumbnail": item.get("thumbnail"),
                        "permalink": item.get("permalink"),
                        "last_updated": item.get("last_updated"),
                        "seller_id": seller_id,
                        "queries": [],
                        "positions": [],
                        "raw_search_item": item,
                        "source_method": run.get("source_method"),
                        "search_scope": run.get("search_scope"),
                        "segment_penalty": _segment_penalty(title, product_type),
                    },
                )
                current["queries"].append(query)
                current["positions"].append(index)

        candidates = list(candidate_map.values())
        return {"candidates": candidates}

    return collect_candidates_node


def build_dedupe_candidates_node():
    async def dedupe_candidates_node(state: ListingDoctorState) -> dict[str, Any]:
        listing = dict(state.get("listing", {}))
        signals = dict(state.get("product_signals", {}))
        warnings = list(state.get("warnings", []))
        evidence = dict(state.get("evidence", {}))
        base_tokens = signals.get("title_tokens", [])
        brand = signals.get("brand")
        listing_price = _safe_float(listing.get("price"))
        exact_like_filtered = 0

        filtered: list[dict[str, Any]] = []
        for candidate in state.get("candidates", []):
            if not _is_probable_item_id(candidate.get("item_id")):
                continue
            if _is_marketplace_noise_title(candidate.get("title")):
                continue
            if _permalink_is_noise(candidate.get("permalink")):
                continue
            candidate_tokens = _tokenize(candidate.get("title"))
            quick_similarity = _weighted_score(
                [
                    (_title_overlap_ratio(base_tokens, candidate_tokens) * 100.0, 0.55),
                    (_brand_match_ratio(brand, candidate.get("brand"), candidate_tokens) * 100.0, 0.2),
                    (_price_closeness_ratio(listing_price, _safe_float(candidate.get("price"))) * 100.0, 0.25),
                ]
            )
            penalty = float(candidate.get("segment_penalty") or 0.0)
            quick_similarity = _clamp(quick_similarity - penalty)
            candidate["quick_similarity"] = quick_similarity
            if _is_near_identical_competitor(
                listing_title=listing.get("title"),
                candidate_title=candidate.get("title"),
                listing_brand=brand,
                candidate_brand=candidate.get("brand"),
                listing_price=listing_price,
                candidate_price=_safe_float(candidate.get("price")),
            ):
                exact_like_filtered += 1
                continue
            if quick_similarity < 22 and len(candidate.get("queries", [])) <= 1:
                continue
            filtered.append(candidate)

        relaxed_threshold_used = False
        if len(filtered) < 3 and len(state.get("candidates", [])) >= 3:
            ranked_candidates = sorted(
                list(state.get("candidates", [])),
                key=lambda entry: float(entry.get("quick_similarity") or 0.0),
                reverse=True,
            )
            selected_ids = {str(entry.get("item_id") or "") for entry in filtered}
            for candidate in ranked_candidates:
                candidate_id = str(candidate.get("item_id") or "")
                if not candidate_id or candidate_id in selected_ids:
                    continue
                if float(candidate.get("quick_similarity") or 0.0) < 14.0:
                    continue
                filtered.append(candidate)
                selected_ids.add(candidate_id)
                relaxed_threshold_used = True
                if len(filtered) >= 3:
                    break

        uncertainties = list(evidence.get("uncertainties", []))
        if exact_like_filtered:
            uncertainties = _append_evidence(
                uncertainties,
                f"Se excluyeron {exact_like_filtered} resultados por parecer el mismo producto exacto y no un comparable similar.",
            )
        if relaxed_threshold_used:
            uncertainties = _append_evidence(
                uncertainties,
                "Se relajo el umbral de similitud para sostener una muestra minima de benchmark.",
            )
        if len(filtered) < 3:
            warnings = _append_warning(
                warnings,
                "La muestra competitiva quedo corta; el benchmark puede tener menor confianza.",
            )
        return {
            "candidates": filtered,
            "warnings": warnings,
            "evidence": {**evidence, "uncertainties": uncertainties},
        }

    return dedupe_candidates_node


def build_shortlist_candidates_node():
    async def shortlist_candidates_node(state: ListingDoctorState) -> dict[str, Any]:
        candidates = list(state.get("candidates", []))
        listing = dict(state.get("listing", {}))
        product_signals = dict(state.get("product_signals", {}))
        base_tokens = product_signals.get("title_tokens", [])
        listing_brand = product_signals.get("brand")
        listing_price = _safe_float(listing.get("price"))
        listing_attr_names = product_signals.get("key_attribute_names", [])
        max_sold = max((_safe_int(item.get("sold_quantity")) or 0 for item in candidates), default=0)
        max_recurrence = max((len(item.get("queries", [])) for item in candidates), default=1)
        config = SEARCH_DEPTH_CONFIG.get(int(state.get("search_depth", 2)), SEARCH_DEPTH_CONFIG[2])

        for candidate in candidates:
            candidate_tokens = _tokenize(candidate.get("title"))
            attribute_lookup = _attribute_lookup(
                candidate.get("raw_search_item", {}).get("attributes", [])
                if isinstance(candidate.get("raw_search_item"), dict)
                else []
            )
            similarity_score = _weighted_score(
                [
                    (_title_overlap_ratio(base_tokens, candidate_tokens) * 100.0, 0.35),
                    (_brand_match_ratio(listing_brand, candidate.get("brand"), candidate_tokens) * 100.0, 0.25),
                    (_attribute_overlap_ratio(listing_attr_names, attribute_lookup) * 100.0, 0.2),
                    (_price_closeness_ratio(listing_price, _safe_float(candidate.get("price"))) * 100.0, 0.2),
                ]
            )
            sold_ratio = (
                ((_safe_int(candidate.get("sold_quantity")) or 0) / max_sold) * 100.0 if max_sold else 50.0
            )
            recurrence_ratio = (len(candidate.get("queries", [])) / max_recurrence) * 100.0 if max_recurrence else 50.0
            avg_position = _average([float(value) for value in candidate.get("positions", []) if value is not None]) or float(config["result_limit"])
            position_score = _clamp(100.0 - ((avg_position - 1.0) / max(config["result_limit"] - 1, 1)) * 100.0)
            exposure_score = _listing_type_proxy_score(candidate.get("listing_type_id"))
            strength_score = _weighted_score(
                [
                    (sold_ratio, 0.35),
                    (recurrence_ratio, 0.25),
                    (position_score, 0.2),
                    (exposure_score, 0.1),
                    (70.0, 0.1),
                ]
            )
            benchmark_score = _weighted_score(
                [
                    (similarity_score, 0.6),
                    (strength_score, 0.4),
                ]
            )
            penalty = _segment_penalty(candidate.get("title"), product_signals.get("product_type"))
            similarity_score = _clamp(similarity_score - penalty)
            benchmark_score = _clamp(benchmark_score - penalty)
            candidate["average_position"] = round(avg_position, 2)
            candidate["similarity_score"] = similarity_score
            candidate["strength_score"] = strength_score
            candidate["benchmark_score"] = benchmark_score
            candidate["segment_penalty"] = penalty

        shortlist_size = min(len(candidates), max(int(state.get("competitor_limit", 8)) * 2, int(state.get("competitor_limit", 8)) + 2, 6))
        shortlisted = sorted(candidates, key=lambda entry: entry.get("benchmark_score", 0), reverse=True)[:shortlist_size]
        partial_analysis = bool(state.get("partial_analysis")) or len(shortlisted) < 3
        evidence = dict(state.get("evidence", {}))
        proxy_points = _append_evidence(
            evidence.get("proxy_points", []),
            "La recurrencia entre multiples busquedas se usa como proxy de presencia competitiva.",
            "La posicion promedio visible dentro de las busquedas se usa como proxy de fuerza relativa.",
        )
        evidence["proxy_points"] = proxy_points
        await _mark_progress(state, STEP_COMPETITOR_DISCOVERY, "completed", "Competidores comparables shortlistados")
        return {
            "shortlisted_candidates": shortlisted,
            "partial_analysis": partial_analysis,
            "evidence": evidence,
        }

    return shortlist_candidates_node


def build_batch_fetch_competitor_details_node(*, market_research: MarketResearchAdapter):
    async def batch_fetch_competitor_details_node(state: ListingDoctorState) -> dict[str, Any]:
        await _mark_progress(state, STEP_COMPETITOR_ENRICHMENT, "running", "Enriqueciendo competidores shortlistados")
        account_key = state["account_key"]
        site_id = state["site_id"]
        warnings = list(state.get("warnings", []))
        evidence = dict(state.get("evidence", {}))
        uncertainties = list(evidence.get("uncertainties", []))
        semaphore = asyncio.Semaphore(5)
        shortlisted = list(state.get("shortlisted_candidates", []))

        async def _fetch(candidate: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                merged = dict(candidate)
                merged["detail_fetch_failed"] = False
                merged["detail_error"] = None
                merged["detail_source"] = "api"
                try:
                    detail = await market_research.get_item_detail(account_key, candidate["item_id"])
                except Exception as exc:
                    detail = {}
                    merged["detail_error"] = _describe_exception(exc)
                    permalink = str(candidate.get("permalink") or "").strip()
                    if permalink and not _permalink_is_noise(permalink):
                        try:
                            detail = await market_research.extract_item_detail_from_public_page(
                                site_id=site_id,
                                permalink=permalink,
                            )
                            merged["detail_source"] = "public_item_page"
                        except Exception as page_exc:
                            merged["detail_fetch_failed"] = True
                            merged["detail_error"] = (
                                f"api: {_describe_exception(exc)} | public_page: {_describe_exception(page_exc)}"
                            )
                    else:
                        merged["detail_fetch_failed"] = True
                permalink = str(candidate.get("permalink") or "").strip()
                needs_public_supplement = bool(
                    permalink
                    and not _permalink_is_noise(permalink)
                    and (
                        not detail
                        or not detail.get("title")
                        or detail.get("price") in (None, "")
                        or not detail.get("thumbnail")
                    )
                )
                if needs_public_supplement:
                    try:
                        public_detail = await market_research.extract_item_detail_from_public_page(
                            site_id=site_id,
                            permalink=permalink,
                        )
                        if isinstance(public_detail, dict):
                            if detail:
                                detail = {
                                    **public_detail,
                                    **{key: value for key, value in detail.items() if value not in (None, "", [], {})},
                                }
                            else:
                                detail = public_detail
                            if merged["detail_source"] == "api":
                                merged["detail_source"] = "api+public_item_page"
                            elif merged["detail_source"] == "public_item_page":
                                merged["detail_source"] = "public_item_page"
                            if detail:
                                merged["detail_fetch_failed"] = False
                    except Exception as supplement_exc:
                        if not detail:
                            merged["detail_fetch_failed"] = True
                        merged["detail_error"] = (
                            f"{merged['detail_error']} | public_supplement: {_describe_exception(supplement_exc)}"
                            if merged["detail_error"]
                            else f"public_supplement: {_describe_exception(supplement_exc)}"
                        )
                description = {}
                try:
                    description = await market_research.get_item_description(account_key, candidate["item_id"])
                except Exception:
                    description = {}
                merged["detail"] = detail
                merged["description"] = str(description.get("plain_text") or "").strip()
                return merged

        competitor_results = await asyncio.gather(*[_fetch(candidate) for candidate in shortlisted], return_exceptions=True)
        enriched: list[dict[str, Any]] = []
        listing_type_ids: set[str] = set()
        partial_detail_count = 0
        for result in competitor_results:
            if isinstance(result, Exception):
                warnings = _append_warning(
                    warnings,
                    f"Un competidor no pudo enriquecerse por completo ({_describe_exception(result)}).",
                )
                continue
            if result.get("detail_fetch_failed"):
                partial_detail_count += 1
            detail = result.get("detail") if isinstance(result.get("detail"), dict) else {}
            listing_type_id = str(detail.get("listing_type_id") or result.get("listing_type_id") or "").strip()
            if listing_type_id:
                listing_type_ids.add(listing_type_id)
            enriched.append(result)

        exposures: list[dict[str, Any]] = []
        try:
            exposures = await market_research.get_listing_exposures(account_key, site_id=site_id)
        except Exception as exc:
            uncertainties = _append_evidence(
                uncertainties,
                f"No se pudo enriquecer la matriz de exposicion de listing types ({_describe_exception(exc)}).",
            )
        exposure_priority_map = {
            str(entry.get("id") or "").strip(): _safe_int(entry.get("priority_in_search"))
            for entry in exposures
            if isinstance(entry, dict)
        }
        listing_type_tasks = {
            listing_type_id: market_research.get_listing_type_detail(
                account_key,
                site_id=site_id,
                listing_type_id=listing_type_id,
            )
            for listing_type_id in listing_type_ids
        }
        listing_type_details: dict[str, dict[str, Any]] = {}
        if listing_type_tasks:
            listing_type_results = await asyncio.gather(*listing_type_tasks.values(), return_exceptions=True)
            for listing_type_id, result in zip(listing_type_tasks.keys(), listing_type_results, strict=False):
                if isinstance(result, Exception):
                    continue
                listing_type_details[listing_type_id] = result if isinstance(result, dict) else {}

        for competitor in enriched:
            detail = competitor.get("detail") if isinstance(competitor.get("detail"), dict) else {}
            listing_type_id = str(detail.get("listing_type_id") or competitor.get("listing_type_id") or "").strip()
            configuration = listing_type_details.get(listing_type_id, {}).get("configuration")
            configuration = configuration if isinstance(configuration, dict) else {}
            listing_exposure = str(configuration.get("listing_exposure") or "").strip() or None
            competitor["listing_type_id"] = listing_type_id or competitor.get("listing_type_id")
            competitor["listing_exposure"] = listing_exposure
            competitor["exposure_priority"] = exposure_priority_map.get(str(listing_exposure or "").strip())

        if partial_detail_count:
            uncertainties = _append_evidence(
                uncertainties,
                f"{partial_detail_count} competidores se sostuvieron con datos parciales de search porque su detalle individual no estuvo disponible.",
            )

        return {
            "competitor_features": enriched,
            "warnings": warnings,
            "evidence": {**evidence, "uncertainties": uncertainties},
        }

    return batch_fetch_competitor_details_node


def build_extract_competitor_features_node():
    async def extract_competitor_features_node(state: ListingDoctorState) -> dict[str, Any]:
        competitors: list[dict[str, Any]] = []
        for competitor in state.get("competitor_features", []):
            detail = competitor.get("detail") if isinstance(competitor.get("detail"), dict) else {}
            raw_search_item = competitor.get("raw_search_item") if isinstance(competitor.get("raw_search_item"), dict) else {}
            attributes = detail.get("attributes") if isinstance(detail.get("attributes"), list) else []
            if not attributes and isinstance(raw_search_item.get("attributes"), list):
                attributes = raw_search_item.get("attributes")
            attribute_lookup = _attribute_lookup(attributes)
            brand = _brand_from_attributes(attributes) or competitor.get("brand")
            title = str(detail.get("title") or competitor.get("title") or "").strip()
            competitor["title"] = title
            competitor["price"] = _safe_float(detail.get("price") or competitor.get("price"))
            competitor["currency_id"] = detail.get("currency_id") or competitor.get("currency_id")
            competitor["sold_quantity"] = _safe_int(detail.get("sold_quantity") or competitor.get("sold_quantity"))
            competitor["status"] = detail.get("status") or competitor.get("status")
            competitor["condition"] = detail.get("condition") or competitor.get("condition")
            competitor["brand"] = brand
            competitor["health"] = _safe_float(detail.get("health"))
            competitor["last_updated"] = detail.get("last_updated") or competitor.get("last_updated")
            competitor["permalink"] = detail.get("permalink") or competitor.get("permalink")
            competitor["thumbnail"] = detail.get("thumbnail") or competitor.get("thumbnail")
            competitor["description"] = str(competitor.get("description") or "").strip()
            competitor["description_present"] = bool(competitor["description"])
            competitor["description_length"] = len(competitor["description"])
            competitor["title_tokens"] = _tokenize(title)
            competitor["attributes"] = attributes
            competitor["attribute_lookup"] = attribute_lookup
            competitor["attributes_count"] = len(attributes)
            competitor["pictures_count"] = len(detail.get("pictures") or []) or (1 if competitor.get("thumbnail") else 0)
            competitors.append(competitor)
        return {"competitor_features": competitors}

    return extract_competitor_features_node


def build_compute_competitor_signals_node():
    async def compute_competitor_signals_node(state: ListingDoctorState) -> dict[str, Any]:
        competitors = list(state.get("competitor_features", []))
        listing = dict(state.get("listing", {}))
        signals = dict(state.get("product_signals", {}))
        listing_price = _safe_float(listing.get("price"))
        base_tokens = signals.get("title_tokens", [])
        listing_brand = signals.get("brand")
        listing_attr_names = signals.get("key_attribute_names", [])
        listing_description_len = len(signals.get("description_text") or "")
        max_sold = max((_safe_int(entry.get("sold_quantity")) or 0 for entry in competitors), default=0)
        max_recurrence = max((len(entry.get("queries", [])) for entry in competitors), default=1)

        for competitor in competitors:
            similarity_score = _weighted_score(
                [
                    (_title_overlap_ratio(base_tokens, competitor.get("title_tokens", [])) * 100.0, 0.35),
                    (
                        _brand_match_ratio(
                            listing_brand,
                            competitor.get("brand"),
                            competitor.get("title_tokens", []),
                        ) * 100.0,
                        0.25,
                    ),
                    (_attribute_overlap_ratio(listing_attr_names, competitor.get("attribute_lookup", {})) * 100.0, 0.2),
                    (_price_closeness_ratio(listing_price, _safe_float(competitor.get("price"))) * 100.0, 0.2),
                ]
            )
            sold_ratio = (((_safe_int(competitor.get("sold_quantity")) or 0) / max_sold) * 100.0) if max_sold else 45.0
            recurrence_ratio = ((len(competitor.get("queries", [])) / max_recurrence) * 100.0) if max_recurrence else 50.0
            avg_position = _average([float(value) for value in competitor.get("positions", []) if value is not None]) or 18.0
            position_score = _clamp(100.0 - ((avg_position - 1.0) / 17.0) * 100.0)
            exposure_score = _exposure_priority_score(
                competitor.get("listing_exposure"),
                _safe_int(competitor.get("exposure_priority")),
            )
            recency_bonus = 75.0 if competitor.get("last_updated") else 55.0
            strength_score = _weighted_score(
                [
                    (sold_ratio, 0.35),
                    (recurrence_ratio, 0.25),
                    (position_score, 0.2),
                    (exposure_score, 0.1),
                    (recency_bonus, 0.1),
                ]
            )
            benchmark_score = _weighted_score(
                [
                    (similarity_score, 0.6),
                    (strength_score, 0.4),
                ]
            )
            growth_proxy = _weighted_score(
                [
                    (recurrence_ratio, 0.45),
                    (sold_ratio, 0.35),
                    (position_score, 0.2),
                ]
            )
            competitor["average_position"] = round(avg_position, 2)
            competitor["similarity_score"] = similarity_score
            competitor["strength_score"] = strength_score
            competitor["benchmark_score"] = benchmark_score
            competitor["growth_proxy"] = growth_proxy
            reasons: list[str] = []
            if len(competitor.get("queries", [])) >= 2:
                reasons.append("Aparece de forma repetida en multiples busquedas.")
            if (_safe_int(competitor.get("sold_quantity")) or 0) > 0:
                reasons.append(f"Ventas visibles: {competitor.get('sold_quantity')}.")
            if competitor.get("listing_exposure"):
                reasons.append(f"Exposicion del listing: {competitor.get('listing_exposure')}.")
            if competitor.get("description_length", 0) > listing_description_len:
                reasons.append("Tiene una descripcion mas profunda que la publicacion analizada.")
            competitor["selection_reason"] = " ".join(reasons[:3]) or "Fue seleccionado por cercania semantica y fuerza competitiva."

        competitors = sorted(competitors, key=lambda entry: entry.get("benchmark_score", 0), reverse=True)
        competitor_limit = int(state.get("competitor_limit", 8))
        competitors = competitors[:competitor_limit]

        prices = [float(entry["price"]) for entry in competitors if entry.get("price") is not None]
        priced_count = len(prices)
        detailed_count = sum(1 for entry in competitors if not entry.get("detail_fetch_failed"))
        benchmark_confidence = _benchmark_confidence(
            competitor_count=len(competitors),
            detailed_count=detailed_count,
            priced_count=priced_count,
        )
        price_benchmark_confidence = _price_benchmark_confidence(
            competitor_count=len(competitors),
            priced_count=priced_count,
        )
        market_summary = dict(state.get("market_summary", {}))
        market_summary.update(
            ListingDoctorMarketSummary(
                total_candidates=len(state.get("candidates", [])),
                shortlisted_competitors=len(competitors),
                query_count=len(state.get("query_bundle", {}).get("search_queries", [])),
                median_price=round(float(median(prices)), 2) if prices else None,
                min_price=round(min(prices), 2) if prices else None,
                max_price=round(max(prices), 2) if prices else None,
                priced_competitors=priced_count,
                detailed_competitors=detailed_count,
                benchmark_confidence=benchmark_confidence,
                price_benchmark_confidence=price_benchmark_confidence,
                dominant_keywords=_top_keywords([str(entry.get("title") or "") for entry in competitors]),
                dominant_brands=_top_brands([str(entry.get("brand") or "") for entry in competitors]),
                search_queries=list(state.get("query_bundle", {}).get("search_queries", [])),
            ).model_dump(mode="json")
        )

        evidence = dict(state.get("evidence", {}))
        proxy_points = _append_evidence(
            evidence.get("proxy_points", []),
            "El growth proxy combina recurrencia, posicion visible y sold_quantity cuando esta disponible.",
            "La fuerza competitiva se estima con similarity_score y strength_score, no con una metrica oficial unica.",
        )
        uncertainties = list(evidence.get("uncertainties", []))
        if not any(entry.get("description_present") for entry in competitors):
            uncertainties = _append_evidence(
                uncertainties,
                "No fue posible recuperar descripciones comparables de la muestra competitiva.",
            )
        if any(entry.get("detail_fetch_failed") for entry in competitors):
            uncertainties = _append_evidence(
                uncertainties,
                "Parte del benchmark competitivo se calculo con metadata parcial de search y no con detalle completo del item.",
            )
        if not any(entry.get("sold_quantity") is not None for entry in competitors):
            uncertainties = _append_evidence(
                uncertainties,
                "La muestra competitiva no expuso sold_quantity de forma consistente; se reforzaron proxies de presencia.",
            )
        evidence["proxy_points"] = proxy_points
        evidence["uncertainties"] = uncertainties
        evidence["factual_points"] = _append_evidence(
            evidence.get("factual_points", []),
            f"Competidores con detalle suficiente: {detailed_count} de {len(competitors)}.",
            f"Competidores con precio usable: {priced_count} de {len(competitors)}.",
            f"Confianza general del benchmark: {benchmark_confidence}.",
            f"Confianza del benchmark de precio: {price_benchmark_confidence}.",
        )

        await _mark_progress(state, STEP_COMPETITOR_ENRICHMENT, "completed", "Competidores enriquecidos y rankeados")
        return {
            "competitor_features": competitors,
            "market_summary": market_summary,
            "evidence": evidence,
        }

    return compute_competitor_signals_node


def build_price_benchmark_node():
    async def price_benchmark_node(state: ListingDoctorState) -> dict[str, Any]:
        await _mark_progress(state, STEP_BENCHMARK_ANALYSIS, "running", "Comparando precio contra el benchmark")
        listing = dict(state.get("listing", {}))
        competitors = list(state.get("competitor_features", []))
        findings = dict(state.get("findings", {}))
        market_summary = dict(state.get("market_summary", {}))
        evidence = dict(state.get("evidence", {}))

        own_price = _safe_float(listing.get("price"))
        prices = [float(entry["price"]) for entry in competitors if entry.get("price") is not None]
        p25 = _percentile(prices, 0.25)
        p75 = _percentile(prices, 0.75)
        median_price = _percentile(prices, 0.5)
        top_prices = [float(entry["price"]) for entry in competitors[:3] if entry.get("price") is not None]
        top_median = _percentile(top_prices, 0.5)
        price_confidence = str(
            market_summary.get("price_benchmark_confidence")
            or _price_benchmark_confidence(competitor_count=len(competitors), priced_count=len(prices))
        )

        scores = dict(state.get("scores", {}))
        uncertainties = list(evidence.get("uncertainties", []))

        if own_price is None:
            scores["price"] = 50.0
            findings["pricing_position"] = [
                "No se pudo leer el precio propio del listing, asi que no corresponde evaluar posicionamiento."
            ]
        elif price_confidence == "low":
            scores["price"] = 60.0
            findings["pricing_position"] = [
                "El benchmark de precio quedo incompleto; todavia no corresponde concluir si el listing esta caro o barato."
            ]
            uncertainties = _append_evidence(
                uncertainties,
                "El benchmark de precio quedo con cobertura insuficiente para ubicar el precio propio con confianza.",
            )
        else:
            distance_component = 50.0
            if median_price not in (None, 0):
                gap_ratio = abs(own_price - float(median_price)) / max(float(median_price), 1.0)
                distance_component = _clamp(100.0 - min(100.0, gap_ratio * 150.0))

            band_component = 55.0
            if p25 is not None and p75 is not None:
                if p25 <= own_price <= p75:
                    band_component = 100.0
                elif market_summary.get("min_price") is not None and market_summary.get("max_price") is not None:
                    min_price = float(market_summary["min_price"])
                    max_price = float(market_summary["max_price"])
                    band_component = 72.0 if min_price <= own_price <= max_price else 30.0

            delta_component = 55.0
            if top_median not in (None, 0):
                top_gap_ratio = abs(own_price - float(top_median)) / max(float(top_median), 1.0)
                delta_component = _clamp(100.0 - min(100.0, top_gap_ratio * 140.0))

            adjustment_component = 70.0
            if listing.get("brand") and median_price is not None and own_price > median_price:
                adjustment_component = 78.0
            elif median_price is not None and own_price < median_price:
                adjustment_component = 74.0

            scores["price"] = _weighted_score(
                [
                    (distance_component, 0.5),
                    (band_component, 0.2),
                    (delta_component, 0.15),
                    (adjustment_component, 0.15),
                ]
            )
            findings["pricing_position"] = [
                _price_band_label(own_price, p25=p25, p75=p75, median_price=median_price)
            ]

        market_summary["median_price"] = round(float(median_price), 2) if median_price is not None else market_summary.get("median_price")
        market_summary["min_price"] = round(min(prices), 2) if prices else market_summary.get("min_price")
        market_summary["max_price"] = round(max(prices), 2) if prices else market_summary.get("max_price")
        market_summary["price_benchmark_confidence"] = price_confidence

        factual_points = _append_evidence(
            evidence.get("factual_points", []),
            (
                f"Precio propio: {own_price:.2f} {listing.get('currency_id') or ''}".strip()
                if own_price is not None
                else "Precio propio no disponible."
            ),
            (
                f"Mediana competitiva: {float(median_price):.2f} {listing.get('currency_id') or ''}".strip()
                if median_price is not None
                else "No hubo suficiente precio competitivo para calcular una mediana estable."
            ),
        )
        evidence["factual_points"] = factual_points
        evidence["uncertainties"] = uncertainties

        return {
            "scores": scores,
            "findings": findings,
            "market_summary": market_summary,
            "evidence": evidence,
        }

    return price_benchmark_node


def build_title_benchmark_node():
    async def title_benchmark_node(state: ListingDoctorState) -> dict[str, Any]:
        listing = dict(state.get("listing", {}))
        market_summary = dict(state.get("market_summary", {}))
        signals = dict(state.get("product_signals", {}))
        findings = dict(state.get("findings", {}))
        evidence = dict(state.get("evidence", {}))

        title = str(listing.get("title") or "")
        title_tokens = signals.get("title_tokens", [])
        dominant_keywords = market_summary.get("dominant_keywords", [])
        key_attribute_names = [str(value).strip() for value in signals.get("key_attribute_names", []) if value]
        attribute_values = [str(value).strip() for value in signals.get("attribute_values", []) if value]

        length_component = _title_length_score(title)
        brand_visible = _contains_all_tokens(title_tokens, listing.get("brand"))
        brand_component = 100.0 if brand_visible else (70.0 if not listing.get("brand") else 35.0)
        type_component = 100.0 if signals.get("product_type") and any(token in title_tokens for token in _tokenize(signals.get("product_type"))) else 45.0
        brand_type_component = _weighted_score([(brand_component, 0.5), (type_component, 0.5)])
        attr_hits = 0
        attr_candidates = [*key_attribute_names[:4], *attribute_values[:4]]
        for attr_name in attr_candidates[:4]:
            attr_tokens = [token for token in _tokenize(attr_name) if token not in {"si", "no"}]
            if attr_tokens and any(token in title_tokens for token in attr_tokens):
                attr_hits += 1
        attribute_basis = attr_candidates[:4]
        attribute_component = 100.0 * (attr_hits / max(1, len(attribute_basis))) if attribute_basis else 55.0
        naming_alignment = 100.0 * (
            len(set(title_tokens).intersection(set(dominant_keywords))) / max(1, len(set(dominant_keywords[:5])))
        ) if dominant_keywords else 60.0
        keyword_balance = _keyword_balance_score(title_tokens)

        scores = dict(state.get("scores", {}))
        scores["title"] = _weighted_score(
            [
                (length_component, 0.15),
                (brand_type_component, 0.2),
                (attribute_component, 0.2),
                (naming_alignment, 0.25),
                (keyword_balance, 0.2),
            ]
        )

        title_gaps: list[str] = []
        if length_component < 70:
            title_gaps.append("La longitud del titulo podria optimizarse para acercarse al rango que mejor compite en el benchmark.")
        if brand_component < 70 and listing.get("brand") and not brand_visible:
            title_gaps.append("La marca no aparece completa en el titulo y conviene hacerla mas visible.")
        if attribute_component < 65 and attribute_basis:
            title_gaps.append("El titulo podria incorporar mejor uno o dos atributos comerciales clave del producto.")
        if naming_alignment < 60 and dominant_keywords:
            title_gaps.append("El naming del titulo podria alinearse mejor con los terminos dominantes del mercado.")
        if keyword_balance < 55:
            title_gaps.append("El titulo muestra margen para balancear mejor claridad y keywords.")
        findings["title_gaps"] = title_gaps[:5]

        proxy_points = _append_evidence(
            evidence.get("proxy_points", []),
            "La alineacion del titulo se compara contra keywords dominantes del benchmark como proxy de naming competitivo.",
        )
        evidence["proxy_points"] = proxy_points

        return {
            "scores": scores,
            "findings": findings,
            "evidence": evidence,
        }

    return title_benchmark_node


def build_attribute_benchmark_node():
    async def attribute_benchmark_node(state: ListingDoctorState) -> dict[str, Any]:
        listing = dict(state.get("listing", {}))
        raw_listing = dict(state.get("raw_listing", {}))
        competitors = list(state.get("competitor_features", []))
        findings = dict(state.get("findings", {}))
        category_attributes = raw_listing.get("category_attributes") if isinstance(raw_listing.get("category_attributes"), list) else []
        listing_attributes = raw_listing.get("attributes") if isinstance(raw_listing.get("attributes"), list) else []

        required = _extract_required_attributes(category_attributes)
        required_lookup = {_normalize_text(item["id"]): item["name"] for item in required}
        listing_attribute_lookup = _attribute_lookup(listing_attributes)
        required_hits = sum(
            1
            for attr_id, attr_name in required_lookup.items()
            if attr_id in listing_attribute_lookup or _normalize_text(attr_name) in listing_attribute_lookup
        )
        required_component = 100.0 * (required_hits / max(1, len(required_lookup))) if required_lookup else 70.0

        common_attrs = _extract_common_attribute_names(competitors)
        common_hits = 0
        for attr_name in common_attrs:
            normalized = _normalize_text(attr_name)
            if normalized in listing_attribute_lookup:
                common_hits += 1
        common_component = 100.0 * (common_hits / max(1, len(common_attrs))) if common_attrs else 65.0

        total_attrs = len(listing_attributes)
        non_empty_attrs = sum(
            1
            for attr in listing_attributes
            if str(attr.get("value_name") or attr.get("value") or attr.get("value_id") or "").strip()
        )
        quality_component = 100.0 * (non_empty_attrs / max(1, total_attrs)) if total_attrs else 30.0

        scores = dict(state.get("scores", {}))
        scores["attributes"] = _weighted_score(
            [
                (required_component, 0.5),
                (common_component, 0.35),
                (quality_component, 0.15),
            ]
        )

        missing_attributes = list(listing.get("missing_attributes", []))
        for attr_name in common_attrs:
            normalized = _normalize_text(attr_name)
            if normalized not in listing_attribute_lookup and attr_name not in missing_attributes:
                missing_attributes.append(attr_name)
        findings["missing_attributes"] = missing_attributes[:12]
        return {
            "scores": scores,
            "findings": findings,
        }

    return attribute_benchmark_node


def build_description_benchmark_node():
    async def description_benchmark_node(state: ListingDoctorState) -> dict[str, Any]:
        listing = dict(state.get("listing", {}))
        signals = dict(state.get("product_signals", {}))
        competitors = list(state.get("competitor_features", []))
        findings = dict(state.get("findings", {}))

        description_text = str(signals.get("description_text") or "")
        description_length = len(description_text)
        presence_component = 100.0 if description_text else 20.0
        structure_component = 100.0 if "\n" in description_text else (70.0 if description_length > 400 else 38.0)
        differentiator_hits = 0
        if listing.get("brand") and _normalize_text(listing.get("brand")) in _normalize_text(description_text):
            differentiator_hits += 1
        for attr_name in signals.get("key_attribute_names", [])[:4]:
            if _normalize_text(attr_name) and _normalize_text(attr_name) in _normalize_text(description_text):
                differentiator_hits += 1
        differentiator_component = _clamp((differentiator_hits / 4.0) * 100.0 if differentiator_hits else 25.0)

        objection_terms = ("garantia", "envio", "uso", "modo", "beneficio", "original")
        objection_hits = sum(1 for term in objection_terms if term in _normalize_text(description_text))
        objection_component = _clamp((objection_hits / len(objection_terms)) * 100.0 if objection_hits else 30.0)

        competitor_avg_description = _average([float(entry.get("description_length", 0)) for entry in competitors if entry.get("description_length") is not None]) or 0.0
        coverage_component = 100.0 if description_length >= competitor_avg_description > 0 else (75.0 if description_length > 0 else 25.0)

        scores = dict(state.get("scores", {}))
        scores["description"] = _weighted_score(
            [
                (presence_component, 0.2),
                (structure_component, 0.2),
                (differentiator_component, 0.2),
                (objection_component, 0.2),
                (coverage_component, 0.2),
            ]
        )

        description_gaps: list[str] = []
        if not description_text:
            description_gaps.append("No hay descripcion util para defender la propuesta comercial.")
            description_gaps.append("Sin descripcion, hoy no se explican diferenciales ni se cubren objeciones frecuentes del comprador.")
        else:
            if structure_component < 70:
                description_gaps.append("La descripcion necesita una estructura mas escaneable.")
            if differentiator_component < 60:
                description_gaps.append("La descripcion no remarca suficientes diferenciales del producto.")
            if objection_component < 55:
                description_gaps.append("La descripcion cubre pocas objeciones frecuentes del comprador.")
        findings["description_gaps"] = description_gaps[:5]
        return {
            "scores": scores,
            "findings": findings,
        }

    return description_benchmark_node


def build_competitiveness_scoring_node():
    async def competitiveness_scoring_node(state: ListingDoctorState) -> dict[str, Any]:
        listing = dict(state.get("listing", {}))
        competitors = list(state.get("competitor_features", []))
        market_summary = dict(state.get("market_summary", {}))
        evidence = dict(state.get("evidence", {}))
        scores = dict(state.get("scores", {}))
        findings = dict(state.get("findings", {}))
        price_confidence = str(market_summary.get("price_benchmark_confidence") or "low")
        benchmark_confidence = str(market_summary.get("benchmark_confidence") or "low")

        benchmark_scores = [float(entry.get("benchmark_score", 0.0)) for entry in competitors]
        benchmark_component = _average(benchmark_scores[:3]) or 55.0
        price_component = scores.get("price", 60.0 if price_confidence == "low" else 50.0)
        health_component = _clamp((_safe_float(listing.get("health")) or 0.65) * 100.0)
        visible_sold_quantities = [float(entry["sold_quantity"]) for entry in competitors if entry.get("sold_quantity") is not None]
        own_sold = float(_safe_int(listing.get("sold_quantity")) or 0)
        traction_component = 55.0
        if visible_sold_quantities:
            competitor_sold_median = _percentile(visible_sold_quantities, 0.5) or 0.0
            if competitor_sold_median > 0:
                traction_component = _clamp((own_sold / competitor_sold_median) * 100.0)
        completeness_component = _weighted_score(
            [
                (scores.get("attributes", 50.0), 0.55),
                (scores.get("description", 50.0), 0.3),
                (100.0 if listing.get("pictures_count", 0) >= 5 else 65.0 if listing.get("pictures_count", 0) >= 3 else 35.0, 0.15),
            ]
        )
        scores["competitiveness"] = _weighted_score(
            [
                (benchmark_component, 0.35),
                (price_component, 0.2),
                (health_component, 0.15),
                (traction_component, 0.15),
                (completeness_component, 0.15),
            ]
        )
        gap_scores = [
            max(0.0, 100.0 - scores.get("title", 0.0)),
            max(0.0, 100.0 - scores.get("price", 0.0)),
            max(0.0, 100.0 - scores.get("attributes", 0.0)),
            max(0.0, 100.0 - scores.get("description", 0.0)),
        ]
        scores["opportunity"] = _weighted_score(
            [
                (_average(gap_scores[:3]) or 50.0, 0.4),
                (max(0.0, 100.0 - scores.get("competitiveness", 0.0)), 0.35),
                (70.0 if listing.get("health_actions") or findings.get("missing_attributes") else 45.0, 0.25),
            ]
        )
        scores["overall"] = _weighted_score(
            [
                (scores.get("title", 0.0), 0.22),
                (scores.get("price", 0.0), 0.18),
                (scores.get("attributes", 0.0), 0.22),
                (scores.get("description", 0.0), 0.18),
                (scores.get("competitiveness", 0.0), 0.2),
            ]
        )

        strengths: list[str] = []
        weaknesses: list[str] = []
        if price_confidence != "low" and scores["price"] >= 70:
            strengths.append("precio relativamente alineado al benchmark")
        if scores["title"] >= 70:
            strengths.append("titulo competitivo frente al naming dominante")
        if scores["attributes"] >= 70:
            strengths.append("atributos con buena completitud relativa")
        if scores["description"] >= 70:
            strengths.append("descripcion mas solida que la media competitiva")
        if listing.get("health") is not None and float(listing["health"]) >= 0.8:
            strengths.append("salud del listing por encima de un umbral saludable")
        if benchmark_confidence == "high":
            strengths.append("benchmark competitivo con buena cobertura de detalle y precio")

        if price_confidence != "low" and scores["price"] < 60:
            weaknesses.append("precio desalineado del rango central del mercado")
        if scores["title"] < 60:
            weaknesses.append("titulo con margen para alinearse mejor al mercado")
        if scores["attributes"] < 60:
            weaknesses.append("faltan atributos frente a lo que muestran los comparables")
        if scores["description"] < 60:
            weaknesses.append("descripcion insuficiente para competir con listings fuertes")
        if listing.get("health_actions"):
            weaknesses.append("hay alertas de calidad activas sobre la publicacion")
        if benchmark_confidence == "low":
            weaknesses.append("el benchmark competitivo aun tiene cobertura parcial y conviene leer con cautela precio y posicionamiento")

        findings["strengths"] = strengths[:6]
        findings["weaknesses"] = weaknesses[:6]

        factual_points = _append_evidence(
            evidence.get("factual_points", []),
            f"Competidores benchmark usados: {len(competitors)}.",
            f"Keywords dominantes observadas: {', '.join(market_summary.get('dominant_keywords', [])[:5]) or 'sin dominancia clara'}.",
        )
        evidence["factual_points"] = factual_points
        await _mark_progress(state, STEP_BENCHMARK_ANALYSIS, "completed", "Benchmark y scores calculados")
        return {
            "scores": scores,
            "findings": findings,
            "evidence": evidence,
        }

    return competitiveness_scoring_node


def build_detect_quick_wins_node():
    async def detect_quick_wins_node(state: ListingDoctorState) -> dict[str, Any]:
        await _mark_progress(state, STEP_OPPORTUNITIES, "running", "Detectando quick wins accionables")
        listing = dict(state.get("listing", {}))
        findings = dict(state.get("findings", {}))
        scores = dict(state.get("scores", {}))
        actions = list(state.get("actions", []))

        if findings.get("title_gaps"):
            actions.append(
                ListingDoctorAction(
                    title="Refuerza el titulo con naming dominante",
                    summary="Ajusta el titulo para incorporar marca, tipo de producto y atributos clave del benchmark.",
                    priority="high",
                    impact="high",
                    effort="low",
                    tags=["alto impacto", "rapido de ejecutar", "titulo"],
                    evidence=findings["title_gaps"][:2],
                ).model_dump(mode="json")
            )
        if findings.get("missing_attributes"):
            actions.append(
                ListingDoctorAction(
                    title="Completa atributos criticos",
                    summary="Carga primero los atributos requeridos y luego los atributos comunes del mercado para cerrar brecha de completitud.",
                    priority="high",
                    impact="high",
                    effort="medium",
                    tags=["alto impacto", "atributos"],
                    evidence=findings["missing_attributes"][:4],
                ).model_dump(mode="json")
            )
        if listing.get("health_actions"):
            actions.append(
                ListingDoctorAction(
                    title="Resuelve alertas de calidad del listing",
                    summary="Atiende las acciones de calidad abiertas porque afectan visibilidad y conversion antes de otras mejoras cosmeticas.",
                    priority="high",
                    impact="high",
                    effort="medium",
                    tags=["alto impacto", "calidad"],
                    evidence=listing.get("health_actions", [])[:3],
                ).model_dump(mode="json")
            )
        if scores.get("description", 0.0) < 60:
            actions.append(
                ListingDoctorAction(
                    title="Reescribe la descripcion para vender mejor",
                    summary="Ordena beneficios, diferenciales y objeciones frecuentes en una descripcion mas escaneable y mas convincente.",
                    priority="medium",
                    impact="high",
                    effort="medium",
                    tags=["descripcion", "conversion"],
                    evidence=findings.get("description_gaps", [])[:3],
                ).model_dump(mode="json")
            )
        return {"actions": actions}

    return detect_quick_wins_node


def build_detect_structural_gaps_node():
    async def detect_structural_gaps_node(state: ListingDoctorState) -> dict[str, Any]:
        listing = dict(state.get("listing", {}))
        findings = dict(state.get("findings", {}))
        scores = dict(state.get("scores", {}))
        competitors = list(state.get("competitor_features", []))
        actions = list(state.get("actions", []))
        market_summary = dict(state.get("market_summary", {}))

        if (
            findings.get("pricing_position")
            and scores.get("price", 0.0) < 65
            and str(market_summary.get("price_benchmark_confidence") or "low") != "low"
        ):
            actions.append(
                ListingDoctorAction(
                    title="Revisa el posicionamiento de precio",
                    summary="Evalua si el diferencial frente a la mediana del mercado esta realmente justificado por marca, bundle o profundidad de oferta.",
                    priority="high",
                    impact="medium",
                    effort="medium",
                    tags=["precio", "benchmark"],
                    evidence=findings["pricing_position"][:2],
                ).model_dump(mode="json")
            )

        competitor_picture_avg = _average([float(item.get("pictures_count", 0)) for item in competitors if item.get("pictures_count") is not None]) or 0.0
        if float(listing.get("pictures_count") or 0) + 1 < competitor_picture_avg:
            actions.append(
                ListingDoctorAction(
                    title="Aumenta profundidad visual",
                    summary="La muestra benchmark usa mas activos visuales; sumar fotos o variantes puede cerrar una brecha estructural de confianza.",
                    priority="medium",
                    impact="medium",
                    effort="medium",
                    tags=["visual", "listado premium"],
                    evidence=[f"Promedio de fotos del benchmark: {competitor_picture_avg:.1f}"],
                ).model_dump(mode="json")
            )

        if scores.get("competitiveness", 0.0) < 55:
            actions.append(
                ListingDoctorAction(
                    title="Replantea el segmento competitivo",
                    summary="Hoy el listing parece competir en un segmento dificil; revisa pack, propuesta de valor y narrativa comercial para reencuadrarlo.",
                    priority="medium",
                    impact="high",
                    effort="high",
                    tags=["segmento", "estrategia"],
                    evidence=findings.get("weaknesses", [])[:3],
                ).model_dump(mode="json")
            )
        return {"actions": actions}

    return detect_structural_gaps_node


def build_prioritize_actions_node():
    async def prioritize_actions_node(state: ListingDoctorState) -> dict[str, Any]:
        actions = list(state.get("actions", []))
        deduped: dict[str, dict[str, Any]] = {}
        for action in actions:
            title = str(action.get("title") or "").strip()
            if not title:
                continue
            if title not in deduped:
                deduped[title] = action
        prioritized = sorted(
            deduped.values(),
            key=lambda action: (
                _action_priority_rank(str(action.get("priority") or "medium")),
                _action_impact_rank(str(action.get("impact") or "medium")),
                _action_effort_rank(str(action.get("effort") or "medium")),
            ),
        )
        await _mark_progress(state, STEP_OPPORTUNITIES, "completed", "Plan de accion priorizado")
        return {"actions": prioritized[:8]}

    return prioritize_actions_node


def build_executive_summary_node(*, llm: Any):
    async def build_executive_summary_node(state: ListingDoctorState) -> dict[str, Any]:
        await _mark_progress(state, STEP_STRATEGY_SYNTHESIS, "running", "Sintetizando diagnostico ejecutivo")
        payload = {
            "listing": state.get("listing", {}),
            "market_summary": state.get("market_summary", {}),
            "scores": state.get("scores", {}),
            "findings": state.get("findings", {}),
            "actions": state.get("actions", [])[:5],
            "evidence": state.get("evidence", {}),
        }
        llm_output = await _invoke_structured(
            llm,
            ExecutiveSummaryOutput,
            system_prompt=STRATEGY_SYNTHESIS_PROMPT,
            human_payload=payload,
            trace_state=state,
            trace_agent="strategy_synthesis_agent",
            trace_node="build_executive_summary.llm",
        )
        if llm_output is not None:
            return {
                "executive_summary": llm_output.executive_summary,
                "detailed_diagnosis": llm_output.detailed_diagnosis[:5],
            }
        return {
            "executive_summary": _fallback_executive_summary(
                dict(state.get("scores", {})),
                dict(state.get("findings", {})),
                dict(state.get("market_summary", {})),
            ),
            "detailed_diagnosis": _fallback_detailed_diagnosis(
                dict(state.get("listing", {})),
                dict(state.get("findings", {})),
                list(state.get("actions", [])),
            ),
        }

    return build_executive_summary_node


def build_detailed_diagnosis_node(*, llm: Any):
    async def build_detailed_diagnosis_node(state: ListingDoctorState) -> dict[str, Any]:
        current_bullets = list(state.get("detailed_diagnosis", []))
        if current_bullets:
            return {"detailed_diagnosis": current_bullets[:5]}
        llm_output = await _invoke_structured(
            llm,
            ExecutiveSummaryOutput,
            system_prompt=STRATEGY_SYNTHESIS_PROMPT,
            human_payload={
                "scores": state.get("scores", {}),
                "findings": state.get("findings", {}),
                "actions": state.get("actions", [])[:5],
            },
            trace_state=state,
            trace_agent="strategy_synthesis_agent",
            trace_node="build_detailed_diagnosis.llm",
        )
        if llm_output is not None and llm_output.detailed_diagnosis:
            return {"detailed_diagnosis": llm_output.detailed_diagnosis[:5]}
        return {
            "detailed_diagnosis": _fallback_detailed_diagnosis(
                dict(state.get("listing", {})),
                dict(state.get("findings", {})),
                list(state.get("actions", [])),
            )
        }

    return build_detailed_diagnosis_node


def build_action_plan_node(*, llm: Any):
    async def build_action_plan_node(state: ListingDoctorState) -> dict[str, Any]:
        llm_output = await _invoke_structured(
            llm,
            PositioningOutput,
            system_prompt=POSITIONING_STRATEGY_PROMPT,
            human_payload={
                "market_summary": state.get("market_summary", {}),
                "scores": state.get("scores", {}),
                "findings": state.get("findings", {}),
                "actions": state.get("actions", [])[:5],
            },
            trace_state=state,
            trace_agent="strategy_synthesis_agent",
            trace_node="build_action_plan.llm",
        )
        ai_suggestions = dict(state.get("ai_suggestions", {}))
        if llm_output is not None:
            ai_suggestions["positioning_strategy"] = llm_output.positioning_strategy
            if not state.get("detailed_diagnosis") and llm_output.diagnosis_bullets:
                await _mark_progress(state, STEP_STRATEGY_SYNTHESIS, "completed", "Diagnostico final sintetizado")
                return {
                    "ai_suggestions": ai_suggestions,
                    "detailed_diagnosis": llm_output.diagnosis_bullets[:5],
                }
            await _mark_progress(state, STEP_STRATEGY_SYNTHESIS, "completed", "Diagnostico final sintetizado")
            return {"ai_suggestions": ai_suggestions}

        ai_suggestions["positioning_strategy"] = _fallback_positioning_strategy(
            dict(state.get("scores", {})),
            dict(state.get("market_summary", {})),
            dict(state.get("findings", {})),
        )
        await _mark_progress(state, STEP_STRATEGY_SYNTHESIS, "completed", "Diagnostico final sintetizado")
        return {"ai_suggestions": ai_suggestions}

    return build_action_plan_node


def build_copywriter_context_node():
    async def build_copywriter_context_node(state: ListingDoctorState) -> dict[str, Any]:
        if not state.get("include_copywriter"):
            await _mark_progress(state, STEP_COPYWRITER, "skipped", "Copywriter opcional omitido")
            return {"copywriter_context": {}}

        await _mark_progress(state, STEP_COPYWRITER, "running", "Preparando contexto de benchmark para Copywriter")
        listing = dict(state.get("listing", {}))
        findings = dict(state.get("findings", {}))
        market_summary = dict(state.get("market_summary", {}))
        actions = list(state.get("actions", []))
        copywriter_context = {
            "product": listing.get("title") or "",
            "brand": listing.get("brand"),
            "country": "Argentina" if state.get("site_id") == "MLA" else state.get("site_id"),
            "confirmed_data": (
                f"Categoria: {listing.get('category_name') or listing.get('category_id') or 'N/D'}\n"
                f"Keywords dominantes: {', '.join(market_summary.get('dominant_keywords', [])[:6]) or 'N/D'}\n"
                f"Atributos faltantes: {', '.join(findings.get('missing_attributes', [])[:6]) or 'ninguno'}\n"
                f"Diferenciales a destacar: {', '.join(findings.get('strengths', [])[:4]) or 'N/D'}\n"
                f"Gaps principales: {', '.join(findings.get('weaknesses', [])[:4]) or 'N/D'}"
            ),
            "commercial_objective": "Optimizar conversion y posicionamiento en Mercado Libre",
            "improvement_notes": "\n".join(
                [
                    "Integra el naming dominante del benchmark.",
                    *findings.get("title_gaps", [])[:2],
                    *findings.get("description_gaps", [])[:2],
                    *[action.get("summary", "") for action in actions[:3]],
                ]
            ).strip(),
        }
        return {"copywriter_context": copywriter_context}

    return build_copywriter_context_node


def build_suggest_titles_with_existing_copywriter_node(*, copywriter_service: CopywriterService):
    async def suggest_titles_with_existing_copywriter_node(state: ListingDoctorState) -> dict[str, Any]:
        if not state.get("include_copywriter"):
            return {}

        warnings = list(state.get("warnings", []))
        ai_suggestions = dict(state.get("ai_suggestions", {}))
        copywriter_context = dict(state.get("copywriter_context", {}))
        request_payload = CopywriterGenerateRequest(
            product=str(copywriter_context.get("product") or ""),
            brand=copywriter_context.get("brand"),
            country=str(copywriter_context.get("country") or "Argentina"),
            confirmed_data=copywriter_context.get("confirmed_data"),
            commercial_objective=copywriter_context.get("commercial_objective"),
        )
        await _trace_event(
            state,
            agent="copywriter_enhancement_agent",
            node="suggest_titles_with_existing_copywriter",
            phase="info",
            message="Invocando CopywriterService.generate_listing.",
            details=request_payload.model_dump(mode="json"),
        )
        try:
            response = await copywriter_service.generate_listing(request_payload)
            ai_suggestions["suggested_titles"] = response.titles[:5]
            if response.description and not ai_suggestions.get("suggested_description"):
                ai_suggestions["suggested_description"] = response.description
            await _trace_event(
                state,
                agent="copywriter_enhancement_agent",
                node="suggest_titles_with_existing_copywriter",
                phase="info",
                message="CopywriterService.generate_listing respondio.",
                details=response.model_dump(mode="json"),
            )
        except Exception:
            warnings = _append_warning(
                warnings,
                "El modulo de copywriter no pudo generar titulos sugeridos en esta ejecucion.",
            )
        return {
            "ai_suggestions": ai_suggestions,
            "warnings": warnings,
        }

    return suggest_titles_with_existing_copywriter_node


def build_suggest_description_with_existing_copywriter_node(*, copywriter_service: CopywriterService):
    async def suggest_description_with_existing_copywriter_node(state: ListingDoctorState) -> dict[str, Any]:
        if not state.get("include_copywriter"):
            return {}

        warnings = list(state.get("warnings", []))
        ai_suggestions = dict(state.get("ai_suggestions", {}))
        copywriter_context = dict(state.get("copywriter_context", {}))
        raw_listing = dict(state.get("raw_listing", {}))
        listing = dict(state.get("listing", {}))
        request_payload = DescriptionEnhanceRequest(
            product_title=str(listing.get("title") or ""),
            current_description=str(raw_listing.get("description") or ""),
            brand=listing.get("brand"),
            category=listing.get("category_name") or listing.get("category_id"),
            price=_safe_float(listing.get("price")),
            currency=listing.get("currency_id"),
            condition=listing.get("condition"),
            attributes=list(raw_listing.get("attributes", [])),
            improvement_notes=str(copywriter_context.get("improvement_notes") or "").strip() or None,
        )
        await _trace_event(
            state,
            agent="copywriter_enhancement_agent",
            node="suggest_description_with_existing_copywriter",
            phase="info",
            message="Invocando CopywriterService.enhance_description.",
            details=request_payload.model_dump(mode="json"),
        )
        try:
            response = await copywriter_service.enhance_description(request_payload)
            ai_suggestions["suggested_description"] = response.enhanced_description
            await _trace_event(
                state,
                agent="copywriter_enhancement_agent",
                node="suggest_description_with_existing_copywriter",
                phase="info",
                message="CopywriterService.enhance_description respondio.",
                details=response.model_dump(mode="json"),
            )
        except Exception:
            warnings = _append_warning(
                warnings,
                "El modulo de copywriter no pudo mejorar la descripcion en esta ejecucion.",
            )

        await _mark_progress(state, STEP_COPYWRITER, "completed", "Sugerencias de copywriter generadas")
        return {
            "ai_suggestions": ai_suggestions,
            "warnings": warnings,
        }

    return suggest_description_with_existing_copywriter_node


def build_result_node():
    async def build_result_node(state: ListingDoctorState) -> dict[str, Any]:
        listing_payload = ListingDoctorListingSummary.model_validate(state.get("listing", {}))
        market_summary_payload = ListingDoctorMarketSummary.model_validate(state.get("market_summary", {}))
        scores_payload = ListingDoctorScores.model_validate(state.get("scores", {}))
        findings_payload = ListingDoctorFindings.model_validate(state.get("findings", {}))
        evidence_payload = ListingDoctorEvidence.model_validate(state.get("evidence", {}))
        ai_suggestions_payload = ListingDoctorAiSuggestions.model_validate(state.get("ai_suggestions", {}))
        competitor_payload = [
            ListingDoctorCompetitorSnapshot(
                item_id=str(entry.get("item_id") or ""),
                title=str(entry.get("title") or ""),
                price=_safe_float(entry.get("price")),
                currency_id=entry.get("currency_id"),
                sold_quantity=_safe_int(entry.get("sold_quantity")),
                status=entry.get("status"),
                brand=entry.get("brand"),
                condition=entry.get("condition"),
                listing_type_id=entry.get("listing_type_id"),
                listing_exposure=entry.get("listing_exposure"),
                health=_safe_float(entry.get("health")),
                attributes_count=int(entry.get("attributes_count") or 0),
                description_present=bool(entry.get("description_present")),
                recurrence=len(entry.get("queries", [])),
                average_position=_safe_float(entry.get("average_position")),
                similarity_score=_safe_float(entry.get("similarity_score")) or 0.0,
                strength_score=_safe_float(entry.get("strength_score")) or 0.0,
                benchmark_score=_safe_float(entry.get("benchmark_score")) or 0.0,
                growth_proxy=_safe_float(entry.get("growth_proxy")),
                selection_reason=str(entry.get("selection_reason") or ""),
                signals=[
                    signal
                    for signal in [
                        f"Recurrencia: {len(entry.get('queries', []))} busquedas" if entry.get("queries") else "",
                        f"Sold quantity visible: {entry.get('sold_quantity')}" if entry.get("sold_quantity") is not None else "",
                        f"Posicion promedio: {entry.get('average_position')}" if entry.get("average_position") is not None else "",
                        f"Exposure: {entry.get('listing_exposure')}" if entry.get("listing_exposure") else "",
                    ]
                    if signal
                ],
                thumbnail=entry.get("thumbnail"),
                permalink=entry.get("permalink"),
                last_updated=entry.get("last_updated"),
            ).model_dump(mode="json")
            for entry in state.get("competitor_features", [])
        ]
        actions_payload = [
            ListingDoctorAction.model_validate(action).model_dump(mode="json")
            for action in state.get("actions", [])
        ]
        result = ListingDoctorResult(
            listing=listing_payload,
            market_summary=market_summary_payload,
            scores=scores_payload,
            executive_summary=str(state.get("executive_summary") or ""),
            detailed_diagnosis=list(state.get("detailed_diagnosis", [])),
            competitor_snapshot=competitor_payload,
            findings=findings_payload,
            actions=actions_payload,
            ai_suggestions=ai_suggestions_payload,
            evidence=evidence_payload,
            generated_at=_now_iso(),
            account_key=state["account_key"],
            site_id=state["site_id"],
            warnings=list(state.get("warnings", [])),
        )
        return {"result": result.model_dump(mode="json")}

    return build_result_node
