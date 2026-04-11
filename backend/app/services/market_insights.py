from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from collections import Counter
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, median
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.config import AgentSettings, get_agent_settings
from app.adapters.market_research import MarketResearchAdapter
from app.core.ai_usage_reporting import create_chat_model, llm_run_config
from app.core.exceptions import BadRequestError, MercadoLibreAPIError
from app.schemas.market_insights import MarketInsightsTraceEntry


STOPWORDS = {
    "a",
    "al",
    "con",
    "de",
    "del",
    "el",
    "en",
    "la",
    "las",
    "lo",
    "los",
    "para",
    "por",
    "sin",
    "un",
    "una",
    "uno",
    "y",
    "o",
}

NOISY_QUERY_TOKENS = {
    "articulo",
    "articulos",
    "categoria",
    "categorias",
    "cosa",
    "cosas",
    "item",
    "items",
    "producto",
    "productos",
}

VERY_GENERIC_KEYWORDS = {
    "accesorio",
    "accesorios",
    "belleza",
    "calzado",
    "cuidado",
    "deporte",
    "deportes",
    "hombre",
    "hombres",
    "hogar",
    "maquillaje",
    "moda",
    "mujer",
    "mujeres",
    "personal",
    "ropa",
    "salud",
    "tecnologia",
}

LOW_SIGNAL_CATEGORY_NAMES = {
    "otros",
    "otras categorias",
    "otras categorias de venta",
    "otros productos",
}

TRACE_LIMIT = 800
logger = logging.getLogger("kaizen-flow.market-insights")

TITLE_NOISE_TOKENS = {
    "cm",
    "color",
    "envio",
    "full",
    "kit",
    "ml",
    "nuevo",
    "oferta",
    "pack",
    "por",
    "unidad",
}

COMMON_COLOR_TOKENS = {
    "azul",
    "beige",
    "blanca",
    "blancas",
    "blanco",
    "blancos",
    "bordo",
    "celeste",
    "dorado",
    "fucsia",
    "gris",
    "lila",
    "marron",
    "marrones",
    "multicolor",
    "multicolores",
    "natural",
    "negra",
    "negras",
    "negro",
    "negros",
    "plateado",
    "rosa",
    "roja",
    "rojas",
    "rojo",
    "rojos",
    "verde",
    "verdes",
    "violeta",
}

ATTRIBUTE_ONLY_ATTRIBUTE_IDS = {
    "BRAND",
    "COLOR",
    "MODEL",
    "LINE",
    "CHARACTER",
}

SERVICE_CATEGORY_TOKENS = {
    "academia",
    "capacitacion",
    "clase",
    "clases",
    "curso",
    "cursos",
    "servicio",
    "servicios",
}

INFRASTRUCTURE_DISCARD_MARKERS = (
    "not found public trends",
    "no se pudo leer una muestra de publicaciones para la categoria",
    "todas las estrategias de acceso fallaron",
    "no se pudieron consultar tendencias de la categoria",
)

CANDIDATE_EXPANSION_PROMPT = """
Sos un analista senior de ecommerce para Mercado Libre.

Tu trabajo es tomar una categoria o necesidad escrita en lenguaje natural y bajarla a oportunidades de producto MUCHO mas concretas.

Reglas:
- devolve solo productos o consultas de busqueda concretas
- no repitas la categoria amplia del usuario
- no devuelvas verticales genericas como "belleza", "hogar", "productos escolares", "productos para hombres"
- usa solo lenguaje que tenga sentido para buscar en Mercado Libre
- apoyate solo en la evidencia entregada: categorias resueltas, subcategorias, tendencias y titulos vistos
- si una idea no esta sustentada por la evidencia, no la incluyas
- prioriza ideas que un vendedor podria publicar y un comprador podria buscar
- para categorias amplias, propone subproductos especificos o variantes concretas

Devolve JSON valido con este formato exacto:
{"queries":["query 1","query 2","query 3"]}
""".strip()


def _normalize_phrase(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    normalized = unicodedata.normalize("NFKD", raw)
    ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _tokenize(value: str | None) -> list[str]:
    return [token for token in _normalize_phrase(value).split() if token]


def _meaningful_tokens(value: str | None) -> list[str]:
    return [
        token
        for token in _tokenize(value)
        if token not in STOPWORDS and token not in NOISY_QUERY_TOKENS
    ]


def _ordered_meaningful_tokens(value: str | None) -> list[str]:
    return [
        token
        for token in _tokenize(value)
        if token not in STOPWORDS and token not in NOISY_QUERY_TOKENS
    ]


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        normalized = _normalize_phrase(cleaned)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(cleaned)
    return deduped


def _singularize_token(token: str) -> str:
    if token.endswith("es") and len(token) > 5:
        return token[:-2]
    if token.endswith("s") and len(token) > 4:
        return token[:-1]
    return token


def _build_query_variants(query: str) -> list[str]:
    base = str(query or "").strip()
    meaningful = _meaningful_tokens(base)
    singular = [_singularize_token(token) for token in meaningful]
    candidates = [
        base,
        " ".join(meaningful),
        " ".join(singular),
        meaningful[0] if meaningful else "",
        singular[0] if singular else "",
    ]
    return _dedupe_preserving_order(candidates)[:5]


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _safe_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value).replace(",", ".")))
    except ValueError:
        return None


def _price_stats(results: list[dict[str, Any]]) -> dict[str, float]:
    prices = [_safe_float(item.get("price")) for item in results]
    valid_prices = [price for price in prices if price is not None]
    if not valid_prices:
        return {}
    return {
        "min": round(min(valid_prices), 2),
        "max": round(max(valid_prices), 2),
        "avg": round(fmean(valid_prices), 2),
        "median": round(float(median(valid_prices)), 2),
    }


def _trend_bucket(rank: int) -> dict[str, str]:
    if rank <= 10:
        return {"id": "fast_growth", "label": "de crecimiento acelerado"}
    if rank <= 30:
        return {"id": "most_wanted", "label": "de alta demanda"}
    return {"id": "popular", "label": "popular"}


def _title_matches_keyword(title: str | None, keyword: str) -> bool:
    keyword_tokens = set(_meaningful_tokens(keyword))
    title_tokens = set(_meaningful_tokens(title))
    if not keyword_tokens or not title_tokens:
        return False
    required_overlap = 1 if len(keyword_tokens) == 1 else min(2, len(keyword_tokens))
    return len(keyword_tokens & title_tokens) >= required_overlap


def _string_or_none(value: Any) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _extract_json_payload(raw_text: str) -> dict[str, Any]:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        parsed = json.loads(raw_text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _base_query_singular(query: str) -> str:
    tokens = _tokenize(query)
    if not tokens:
        return str(query or "").strip()
    tokens[-1] = _singularize_token(tokens[-1])
    return " ".join(tokens).strip()


def _is_broad_query(query: str) -> bool:
    meaningful = _meaningful_tokens(query)
    if not meaningful:
        return True
    if len(meaningful) == 1:
        return meaningful[0] in VERY_GENERIC_KEYWORDS
    if any(token in VERY_GENERIC_KEYWORDS for token in meaningful):
        return True
    return any(token in {"producto", "productos"} for token in _tokenize(query))


def _child_categories_from_detail(detail: dict[str, Any]) -> list[dict[str, Any]]:
    children = detail.get("children_categories") if isinstance(detail.get("children_categories"), list) else []
    normalized_children: list[dict[str, Any]] = []
    for entry in children:
        if not isinstance(entry, dict):
            continue
        child_id = str(entry.get("id") or "").strip()
        child_name = str(entry.get("name") or "").strip()
        if not child_id or not child_name:
            continue
        normalized_children.append(
            {
                "id": child_id,
                "name": child_name,
                "total_items_in_this_category": _safe_int(entry.get("total_items_in_this_category")),
            }
        )
    return normalized_children


def _clean_title_signal(title: str, *, query: str, category_name: str | None) -> str | None:
    raw_title = str(title or "").strip()
    if not raw_title:
        return None
    title_tokens = [
        token
        for token in _ordered_meaningful_tokens(raw_title)
        if token not in TITLE_NOISE_TOKENS
    ]
    if len(title_tokens) < 2:
        return None
    alpha_title_tokens = [token for token in title_tokens if re.search(r"[a-z]", token)]
    if len(alpha_title_tokens) < 2:
        return None

    base_query_tokens = [_singularize_token(token) for token in _ordered_meaningful_tokens(query)]
    category_tokens = [_singularize_token(token) for token in _ordered_meaningful_tokens(category_name)]
    title_singular = [_singularize_token(token) for token in title_tokens]

    if _is_broad_query(query):
        filtered = [token for token in title_tokens if token not in VERY_GENERIC_KEYWORDS]
        candidate = " ".join(filtered[:3]).strip()
    else:
        anchors = [token for token in [*base_query_tokens, *category_tokens] if token]
        anchor_set = set(anchors)
        anchor_index = next((index for index, token in enumerate(title_singular) if token in anchor_set), None)
        if anchor_index is None:
            return None
        else:
            candidate_tokens = [title_tokens[anchor_index]]
            cursor = anchor_index + 1
            while cursor < len(title_tokens) and len(candidate_tokens) < 3:
                token = title_tokens[cursor]
                if token in TITLE_NOISE_TOKENS:
                    cursor += 1
                    continue
                candidate_tokens.append(token)
                cursor += 1
            if len(candidate_tokens) == 1 and anchor_index > 0:
                previous = title_tokens[anchor_index - 1]
                if previous not in TITLE_NOISE_TOKENS:
                    candidate_tokens.insert(0, previous)
            candidate = " ".join(candidate_tokens).strip()

    candidate_tokens = _meaningful_tokens(candidate)
    if len(candidate_tokens) < 2:
        return None
    if len([token for token in candidate_tokens if re.search(r"[a-z]", token)]) < 2:
        return None
    if _normalize_phrase(candidate) == _normalize_phrase(query):
        return None
    return candidate


def _attribute_value_tokens(attributes: list[dict[str, Any]]) -> set[str]:
    tokens: set[str] = set()
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        attribute_id = str(attribute.get("id") or "").strip().upper()
        if attribute_id not in ATTRIBUTE_ONLY_ATTRIBUTE_IDS:
            continue
        tokens.update(_meaningful_tokens(attribute.get("value_name")))
    return tokens


def _is_infrastructure_discard(reason: str | None) -> bool:
    normalized = _normalize_phrase(reason)
    if not normalized:
        return False
    return any(marker in normalized for marker in INFRASTRUCTURE_DISCARD_MARKERS)


class MarketInsightsRunStore:
    def __init__(self, base_dir: Path, *, user_id: int) -> None:
        self._base_dir = Path(base_dir) / f"user_{user_id}"
        self._runs_dir = self._base_dir / "runs"
        self._logs_dir = self._base_dir / "logs"
        self._runs_dir.mkdir(parents=True, exist_ok=True)
        self._logs_dir.mkdir(parents=True, exist_ok=True)

    def _run_path(self, run_id: str) -> Path:
        return self._runs_dir / f"{run_id}.json"

    def _log_path(self, run_id: str) -> Path:
        return self._logs_dir / f"{run_id}.md"

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def create_run(
        self,
        *,
        run_id: str,
        account_key: str,
        site_id: str,
        natural_query: str,
        limit: int,
    ) -> dict[str, Any]:
        timestamp = _now_iso()
        record = {
            "run_id": run_id,
            "status": "running",
            "created_at": timestamp,
            "updated_at": timestamp,
            "account_key": account_key,
            "site_id": site_id,
            "natural_query": natural_query,
            "limit": limit,
            "trace": [],
            "log_file_path": str(self._log_path(run_id)),
            "result": None,
            "error_message": None,
        }
        self._write_json(self._run_path(run_id), record)
        return record

    def save_run(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload["updated_at"] = _now_iso()
        payload.setdefault("log_file_path", str(self._log_path(run_id)))
        self._write_json(self._run_path(run_id), payload)
        return payload

    def write_execution_log(self, run_id: str, payload: dict[str, Any]) -> Path:
        log_path = self._log_path(run_id)
        trace = payload.get("trace") if isinstance(payload.get("trace"), list) else []
        result = payload.get("result")

        lines: list[str] = [
            f"# Market Insights Execution Log - {run_id}",
            "",
            "## Metadata",
            f"- status: {payload.get('status')}",
            f"- created_at: {payload.get('created_at')}",
            f"- updated_at: {payload.get('updated_at')}",
            f"- account_key: {payload.get('account_key')}",
            f"- site_id: {payload.get('site_id')}",
            f"- natural_query: {payload.get('natural_query')}",
            f"- limit: {payload.get('limit')}",
            f"- log_file_path: {log_path}",
            "",
        ]

        if payload.get("error_message"):
            lines.extend(["## Error", str(payload.get("error_message")), ""])

        lines.extend(["## Trace", ""])
        if not trace:
            lines.extend(["No trace events were recorded.", ""])
        else:
            for entry in trace:
                if not isinstance(entry, dict):
                    continue
                lines.extend(
                    [
                        f"### #{entry.get('sequence')} {entry.get('stage')} / {entry.get('phase')}",
                        f"- timestamp: {entry.get('timestamp')}",
                        f"- message: {entry.get('message')}",
                    ]
                )
                details = entry.get("details")
                if details is not None:
                    lines.extend(
                        [
                            "",
                            "```json",
                            json.dumps(details, ensure_ascii=False, indent=2),
                            "```",
                        ]
                    )
                lines.append("")

        if isinstance(result, dict):
            lines.extend(
                [
                    "## Final Result",
                    "",
                    "```json",
                    json.dumps(result, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )

        log_path.write_text("\n".join(lines), encoding="utf-8")
        return log_path


class MarketInsightsService:
    def __init__(
        self,
        *,
        user_id: int,
        market_research: MarketResearchAdapter,
        default_site_id: str = "MLA",
        agent_settings: AgentSettings | None = None,
    ) -> None:
        self._user_id = user_id
        self._market_research = market_research
        self._default_site_id = str(default_site_id or "MLA").strip().upper()
        self._agent_settings = agent_settings or get_agent_settings()
        self._run_store = MarketInsightsRunStore(
            self._agent_settings.memory_dir.parent / "market_insights",
            user_id=user_id,
        )
        self._llm = None
        self._active_run_id_ctx: ContextVar[str | None] = ContextVar(
            "market_insights_active_run_id",
            default=None,
        )
        self._trace_ctx: ContextVar[list[dict[str, Any]] | None] = ContextVar(
            "market_insights_trace_buffer",
            default=None,
        )

    def _get_llm(self):
        if self._llm is not None:
            return self._llm

        self._agent_settings.validate_runtime()
        self._llm = create_chat_model(
            self._agent_settings,
            model=self._agent_settings.google_model,
            temperature=0.1,
            feature="market_insights",
            max_retries=2,
        )
        return self._llm

    def _generate_run_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"market-insights-{timestamp}-{uuid4().hex[:6]}"

    def _trace_buffer(self) -> list[dict[str, Any]]:
        buffer = self._trace_ctx.get()
        if buffer is None:
            buffer = []
            self._trace_ctx.set(buffer)
        return buffer

    def _append_trace(self, *, stage: str, phase: str, message: str, details: Any | None = None) -> None:
        buffer = self._trace_buffer()
        entry = MarketInsightsTraceEntry(
            sequence=len(buffer) + 1,
            timestamp=_now_iso(),
            stage=stage,
            phase=phase,
            message=message,
            details=details,
        ).model_dump(mode="json")
        buffer.append(entry)
        if len(buffer) > TRACE_LIMIT:
            del buffer[:-TRACE_LIMIT]
        logger.info(
            "market_insights_trace run=%s stage=%s phase=%s message=%s details=%s",
            self._active_run_id_ctx.get(),
            stage,
            phase,
            message,
            details,
        )

    def _select_focus_categories(
        self,
        *,
        query: str,
        categories: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if len(categories) <= 1:
            return categories

        query_norm = _normalize_phrase(query)
        singular_query_norm = _normalize_phrase(_base_query_singular(query))
        query_tokens = set(_meaningful_tokens(query))

        def _score(category: dict[str, Any]) -> float:
            category_name_norm = _normalize_phrase(category.get("category_name"))
            domain_name_norm = _normalize_phrase(category.get("domain_name"))
            category_tokens = set(_meaningful_tokens(category.get("category_name")))
            domain_tokens = set(_meaningful_tokens(category.get("domain_name")))
            path_tokens = {
                token
                for entry in category.get("category_path") or []
                for token in _meaningful_tokens(entry)
            }
            context_tokens = category_tokens | domain_tokens | path_tokens
            extra_tokens = {
                token
                for token in context_tokens
                if token not in query_tokens and token not in VERY_GENERIC_KEYWORDS
            }
            service_like = bool(context_tokens & SERVICE_CATEGORY_TOKENS)

            score = 0.0
            if category_name_norm in {query_norm, singular_query_norm}:
                score += 3.0
            if domain_name_norm in {query_norm, singular_query_norm}:
                score += 2.0
            score += 0.9 * len(query_tokens & category_tokens)
            score += 1.1 * len(query_tokens & domain_tokens)
            score += 0.8 * len(query_tokens & path_tokens)
            score -= 0.25 * len(extra_tokens)
            if category.get("resolved_by") == "search_fallback":
                score -= 0.35
            if category.get("resolved_by") == "public_listing_inference":
                score -= 0.1
            if category.get("is_low_signal_category"):
                score -= 0.4
            if service_like:
                score -= 3.2
            if (_safe_int(category.get("total_items_in_this_category")) or 0) >= 1000:
                score += 0.2
            return round(score, 2)

        ranked = sorted(categories, key=_score, reverse=True)
        if len(ranked) == 1:
            selected = ranked
        else:
            score_gap = _score(ranked[0]) - _score(ranked[1])
            top_exact = _normalize_phrase(ranked[0].get("category_name")) in {query_norm, singular_query_norm}
            selected = ranked[:1] if (top_exact and score_gap >= 1.0) or score_gap >= 1.25 else ranked[:2]

        self._append_trace(
            stage="category_resolution",
            phase="info",
            message="Categorias priorizadas segun relevancia con la consulta.",
            details={
                "query": query,
                "ranked_categories": [
                    {
                        "category_id": category.get("category_id"),
                        "category_name": category.get("category_name"),
                        "score": _score(category),
                    }
                    for category in ranked
                ],
                "selected_category_ids": [category.get("category_id") for category in selected],
            },
        )
        return selected

    async def _get_public_listing_titles(
        self,
        *,
        site_id: str,
        query: str,
        stage: str,
        trace_context: dict[str, Any] | None = None,
        limit: int = 18,
    ) -> tuple[list[str], dict[str, Any] | None, str | None]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return [], None, "La consulta publica quedo vacia."

        try:
            payload = await self._market_research.search_items_via_web_listing(
                site_id=site_id,
                query=normalized_query,
                limit=limit,
            )
        except MercadoLibreAPIError as exc:
            self._append_trace(
                stage=stage,
                phase="failed",
                message="Fallo la consulta al listado publico de Mercado Libre.",
                details={
                    **(trace_context or {}),
                    "query_used": normalized_query,
                    "error": exc.message,
                },
            )
            return [], None, exc.message

        results = payload.get("results") if isinstance(payload, dict) else []
        titles = _dedupe_preserving_order(
            [
                str(item.get("title") or "").strip()
                for item in results
                if isinstance(item, dict) and str(item.get("title") or "").strip()
            ]
        )[:limit]
        self._append_trace(
            stage=stage,
            phase="info",
            message="Se recuperaron titulos desde el listado publico.",
            details={
                **(trace_context or {}),
                "query_used": normalized_query,
                "title_count": len(titles),
                "source_method": payload.get("source_method") if isinstance(payload, dict) else None,
                "source_url": payload.get("source_url") if isinstance(payload, dict) else None,
            },
        )
        return titles, payload if isinstance(payload, dict) else None, None

    async def _predict_categories_from_queries(
        self,
        *,
        account_key: str,
        site_id: str,
        queries: list[str],
        resolved_by: str,
    ) -> list[dict[str, Any]]:
        normalized_queries = _dedupe_preserving_order(queries)[:6]
        if not normalized_queries:
            return []

        predictions = await asyncio.gather(
            *[
                self._market_research.predict_category(
                    account_key,
                    site_id=site_id,
                    query=current_query,
                    limit=3,
                )
                for current_query in normalized_queries
            ],
            return_exceptions=True,
        )

        category_hits: Counter[str] = Counter()
        category_examples: dict[str, dict[str, Any]] = {}
        for current_query, prediction in zip(normalized_queries, predictions, strict=False):
            if isinstance(prediction, Exception):
                continue
            top_suggestion = next(
                (entry for entry in prediction if isinstance(entry, dict) and str(entry.get("category_id") or "").strip()),
                None,
            )
            if top_suggestion is None:
                continue
            category_id = str(top_suggestion.get("category_id") or "").strip()
            category_hits[category_id] += 1
            category_examples.setdefault(
                category_id,
                {
                    "category_id": category_id,
                    "category_name": _string_or_none(top_suggestion.get("category_name")),
                    "domain_id": _string_or_none(top_suggestion.get("domain_id")),
                    "domain_name": _string_or_none(top_suggestion.get("domain_name")),
                    "resolved_by": resolved_by,
                    "query_used": current_query,
                    "search_hit_count": 0,
                    "fallback_titles": [],
                },
            )
            category_examples[category_id]["search_hit_count"] = category_hits[category_id]
            fallback_titles = category_examples[category_id].setdefault("fallback_titles", [])
            if current_query not in fallback_titles:
                fallback_titles.append(current_query)

        return [
            category_examples[category_id]
            for category_id, _ in category_hits.most_common(3)
        ]

    def _category_context_queries(self, *, query: str, category: dict[str, Any]) -> list[str]:
        category_name = _string_or_none(category.get("category_name"))
        candidates = [query]
        if category_name:
            candidates.append(category_name)
            if _is_broad_query(query):
                candidates.append(f"{query} {category_name}")
        return _dedupe_preserving_order(candidates)

    def _is_attribute_only_candidate(
        self,
        *,
        keyword: str,
        query: str,
        predicted_attributes: list[dict[str, Any]],
    ) -> bool:
        keyword_tokens = set(_meaningful_tokens(keyword))
        query_tokens = set(_meaningful_tokens(query))
        extra_tokens = {token for token in keyword_tokens if token not in query_tokens}
        if not extra_tokens:
            return False

        attribute_tokens = _attribute_value_tokens(predicted_attributes)
        if extra_tokens.issubset(attribute_tokens) and len(extra_tokens) <= 2:
            return True
        return bool(extra_tokens and extra_tokens.issubset(COMMON_COLOR_TOKENS))

    async def _build_query_only_candidate_pool(
        self,
        *,
        account_key: str,
        site_id: str,
        query: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        discarded: list[dict[str, Any]] = []
        public_titles, _, public_error = await self._get_public_listing_titles(
            site_id=site_id,
            query=query,
            stage="candidate_pool",
            trace_context={"mode": "query_only"},
            limit=18,
        )
        if public_error:
            discarded.append(
                {
                    "keyword": query,
                    "category_id": None,
                    "category_name": None,
                    "reason": f"No se pudo leer una muestra publica para la consulta ({public_error}).",
                }
            )

        site_trends: list[str] = []
        try:
            trends = await self._market_research.get_trends(account_key, site_id=site_id)
            site_trends = _dedupe_preserving_order(
                [
                    str(entry.get("keyword") or entry.get("query") or entry.get("name") or "").strip()
                    for entry in trends
                    if isinstance(entry, dict)
                ]
            )[:30]
        except MercadoLibreAPIError as exc:
            discarded.append(
                {
                    "keyword": query,
                    "category_id": None,
                    "category_name": None,
                    "reason": f"No se pudieron consultar tendencias generales del sitio ({exc.message}).",
                }
            )
            self._append_trace(
                stage="candidate_pool",
                phase="failed",
                message="Fallo la lectura de tendencias generales del sitio.",
                details={"query": query, "site_id": site_id, "error": exc.message},
            )

        title_candidates = _dedupe_preserving_order(
            [_clean_title_signal(title, query=query, category_name=None) for title in public_titles]
        )[:8]
        ai_candidates = await self._expand_candidates_with_ai(
            query=query,
            contexts=[],
            site_trends=site_trends,
            public_titles=public_titles,
        )

        candidate_pool = [
            {"query": candidate_query, "source": "public_title", "source_category_id": None, "source_category_name": None}
            for candidate_query in title_candidates
            if candidate_query
        ]
        candidate_pool.extend(
            [
                {
                    "query": candidate_query,
                    "source": "ai_expansion",
                    "source_category_id": None,
                    "source_category_name": None,
                }
                for candidate_query in ai_candidates
                if candidate_query
            ]
        )

        deduped_pool: list[dict[str, Any]] = []
        seen_queries: set[str] = set()
        for entry in candidate_pool:
            raw_query = str(entry.get("query") or "").strip()
            normalized = _normalize_phrase(raw_query)
            if not raw_query or not normalized or normalized in seen_queries:
                continue
            if normalized == _normalize_phrase(query):
                continue
            seen_queries.add(normalized)
            deduped_pool.append(entry)

        self._append_trace(
            stage="candidate_pool",
            phase="completed",
            message="Pool de candidatos construido desde la consulta amplia.",
            details={
                "query": query,
                "candidate_count": len(deduped_pool),
                "site_trend_count": len(site_trends),
                "public_title_count": len(public_titles),
                "candidates": deduped_pool,
                "discarded": discarded,
            },
        )
        return deduped_pool[:16], discarded

    def _filter_user_facing_discards(
        self,
        *,
        discarded: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for entry in discarded:
            if not isinstance(entry, dict):
                continue
            keyword = _string_or_none(entry.get("keyword"))
            category_id = _string_or_none(entry.get("category_id")) or ""
            reason = _string_or_none(entry.get("reason"))
            if not reason:
                continue
            if _is_infrastructure_discard(reason):
                continue
            if keyword and len([token for token in _meaningful_tokens(keyword) if re.search(r"[a-z]", token)]) < 2:
                continue
            dedupe_key = (_normalize_phrase(keyword), category_id, _normalize_phrase(reason))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            filtered.append(entry)
        return filtered

    async def build_trend_report(
        self,
        *,
        account_key: str,
        site_id: str | None,
        natural_query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        query = str(natural_query or "").strip()
        if not query:
            raise BadRequestError("Debes indicar una categoria o idea de producto para investigar tendencias.")

        normalized_site = str(site_id or self._default_site_id).strip().upper() or self._default_site_id
        capped_limit = min(max(limit, 1), 8)
        run_id = self._generate_run_id()
        run_token = self._active_run_id_ctx.set(run_id)
        trace_token = self._trace_ctx.set([])
        record = self._run_store.create_run(
            run_id=run_id,
            account_key=account_key,
            site_id=normalized_site,
            natural_query=query,
            limit=capped_limit,
        )
        self._append_trace(
            stage="service",
            phase="started",
            message="Inicio del reporte de market insights.",
            details={
                "account_key": account_key,
                "site_id": normalized_site,
                "natural_query": query,
                "limit": capped_limit,
            },
        )

        try:
            raw_categories, resolution_notes = await self._resolve_categories(
                account_key=account_key,
                site_id=normalized_site,
                query=query,
            )
            categories = await self._enrich_categories(account_key=account_key, raw_categories=raw_categories)
            categories = self._select_focus_categories(query=query, categories=categories)
            self._append_trace(
                stage="category_enrichment",
                phase="completed",
                message="Categorias enriquecidas.",
                details={
                    "resolved_categories": categories,
                    "resolution_notes": resolution_notes,
                },
            )
            validated_opportunities, discarded_signals = await self._collect_opportunities(
                account_key=account_key,
                site_id=normalized_site,
                query=query,
                categories=categories,
                limit=capped_limit,
            )
            user_facing_discarded_signals = self._filter_user_facing_discards(discarded=discarded_signals)

            result = {
                "ok": True,
                "run_id": run_id,
                "site_id": normalized_site,
                "input_query": query,
                "resolution_notes": resolution_notes,
                "resolved_categories": categories,
                "validated_opportunities": validated_opportunities[:capped_limit],
                "discarded_signals": user_facing_discarded_signals[:10],
                "summary": {
                    "resolved_category_count": len(categories),
                    "validated_opportunity_count": min(len(validated_opportunities), capped_limit),
                    "discarded_signal_count": len(user_facing_discarded_signals),
                },
                "execution_trace": list(self._trace_buffer()),
                "log_file_path": record.get("log_file_path"),
            }
            self._append_trace(
                stage="service",
                phase="completed",
                message="Reporte de market insights finalizado.",
                details=result["summary"],
            )
            payload = {
                **record,
                "status": "completed",
                "trace": list(self._trace_buffer()),
                "result": {
                    **result,
                    "execution_trace": list(self._trace_buffer()),
                },
                "error_message": None,
            }
            payload = self._run_store.save_run(run_id, payload)
            self._run_store.write_execution_log(run_id, payload)
            return {
                **result,
                "execution_trace": list(self._trace_buffer()),
                "log_file_path": payload.get("log_file_path"),
            }
        except Exception as exc:
            self._append_trace(
                stage="service",
                phase="failed",
                message="La corrida de market insights fallo.",
                details={"error": str(exc), "exception_type": exc.__class__.__name__},
            )
            payload = {
                **record,
                "status": "failed",
                "trace": list(self._trace_buffer()),
                "result": None,
                "error_message": str(exc),
            }
            payload = self._run_store.save_run(run_id, payload)
            self._run_store.write_execution_log(run_id, payload)
            raise
        finally:
            self._active_run_id_ctx.reset(run_token)
            self._trace_ctx.reset(trace_token)

    async def _resolve_categories(
        self,
        *,
        account_key: str,
        site_id: str,
        query: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        self._append_trace(
            stage="category_resolution",
            phase="started",
            message="Iniciando resolucion de categorias.",
            details={"query": query, "site_id": site_id},
        )
        notes: list[dict[str, Any]] = []
        categories: list[dict[str, Any]] = []
        seen_categories: set[str] = set()

        for variant in _build_query_variants(query):
            try:
                suggestions = await self._market_research.predict_category(
                    account_key,
                    site_id=site_id,
                    query=variant,
                    limit=6,
                )
            except MercadoLibreAPIError as exc:
                notes.append(
                    {
                        "stage": "category_predictor",
                        "query_used": variant,
                        "status": "error",
                        "message": exc.message,
                    }
                )
                self._append_trace(
                    stage="category_resolution",
                    phase="failed",
                    message="Fallo una consulta al category predictor.",
                    details={"query_used": variant, "error": exc.message},
                )
                continue

            if not suggestions:
                notes.append(
                    {
                        "stage": "category_predictor",
                        "query_used": variant,
                        "status": "empty",
                    }
                )
                self._append_trace(
                    stage="category_resolution",
                    phase="info",
                    message="El category predictor no devolvio sugerencias para una variante.",
                    details={"query_used": variant},
                )
                continue

            notes.append(
                {
                    "stage": "category_predictor",
                    "query_used": variant,
                    "status": "ok",
                    "suggestion_count": len(suggestions),
                }
            )
            self._append_trace(
                stage="category_resolution",
                phase="info",
                message="El category predictor devolvio sugerencias.",
                details={"query_used": variant, "suggestions": suggestions[:6]},
            )

            for suggestion in suggestions:
                category_id = str(suggestion.get("category_id") or "").strip()
                if not category_id or category_id in seen_categories:
                    continue
                seen_categories.add(category_id)
                categories.append(
                    {
                        "category_id": category_id,
                        "category_name": _string_or_none(
                            suggestion.get("category_name")
                            or suggestion.get("category")
                            or suggestion.get("name")
                        ),
                        "domain_id": _string_or_none(suggestion.get("domain_id")),
                        "domain_name": _string_or_none(suggestion.get("domain_name")),
                        "resolved_by": "category_predictor",
                        "query_used": variant,
                    }
                )
                if len(categories) >= 3:
                    self._append_trace(
                        stage="category_resolution",
                        phase="completed",
                        message="Se alcanzaron suficientes categorias resueltas desde el predictor.",
                        details={"categories": categories},
                    )
                    return categories, notes

        if categories:
            self._append_trace(
                stage="category_resolution",
                phase="completed",
                message="Se resolvieron categorias desde el predictor.",
                details={"categories": categories},
            )
            return categories, notes

        fallback_results: list[dict[str, Any]] = []
        try:
            fallback_payload = await self._market_research.search_items(
                account_key,
                site_id=site_id,
                query=query,
                category_id=None,
                limit=12,
            )
            results = fallback_payload.get("results") if isinstance(fallback_payload, dict) else []
            fallback_results = [item for item in results if isinstance(item, dict)]
        except MercadoLibreAPIError as exc:
            notes.append(
                {
                    "stage": "search_fallback",
                    "query_used": query,
                    "status": "error",
                    "message": exc.message,
                }
            )
            self._append_trace(
                stage="category_resolution",
                phase="failed",
                message="Fallo el fallback por busqueda para resolver categorias.",
                details={"query_used": query, "error": exc.message},
            )

        category_counter: Counter[str] = Counter()
        category_titles: dict[str, list[str]] = {}
        for item in fallback_results:
            category_id = str(item.get("category_id") or "").strip()
            if not category_id:
                continue
            category_counter[category_id] += 1
            category_titles.setdefault(category_id, [])
            title = str(item.get("title") or "").strip()
            if title:
                category_titles[category_id].append(title)

        if category_counter:
            notes.append(
                {
                    "stage": "search_fallback",
                    "query_used": query,
                    "status": "ok",
                    "category_count": len(category_counter),
                }
            )

            for category_id, hit_count in category_counter.most_common(3):
                categories.append(
                    {
                        "category_id": category_id,
                        "category_name": None,
                        "domain_id": None,
                        "domain_name": None,
                        "resolved_by": "search_fallback",
                        "query_used": query,
                        "search_hit_count": hit_count,
                        "fallback_titles": category_titles.get(category_id, [])[:3],
                    }
                )

            self._append_trace(
                stage="category_resolution",
                phase="completed",
                message="Categorias resueltas via fallback de busqueda.",
                details={"categories": categories, "category_counter": dict(category_counter)},
            )
            return categories, notes

        notes.append(
            {
                "stage": "search_fallback",
                "query_used": query,
                "status": "empty",
            }
        )
        self._append_trace(
            stage="category_resolution",
            phase="info",
            message="La busqueda API no alcanzo para inferir categorias; se intenta listado publico.",
            details={"query_used": query},
        )

        public_titles, _, public_error = await self._get_public_listing_titles(
            site_id=site_id,
            query=query,
            stage="category_resolution",
            trace_context={"mode": "public_listing_inference"},
            limit=12,
        )
        if public_error:
            notes.append(
                {
                    "stage": "public_listing_inference",
                    "query_used": query,
                    "status": "error",
                    "message": public_error,
                }
            )
            return [], notes

        inferred_categories = await self._predict_categories_from_queries(
            account_key=account_key,
            site_id=site_id,
            queries=public_titles,
            resolved_by="public_listing_inference",
        )
        if not inferred_categories:
            notes.append(
                {
                    "stage": "public_listing_inference",
                    "query_used": query,
                    "status": "empty",
                }
            )
            self._append_trace(
                stage="category_resolution",
                phase="failed",
                message="El listado publico tampoco permitio inferir categorias utiles.",
                details={"query_used": query, "sample_titles": public_titles[:6]},
            )
            return [], notes

        notes.append(
            {
                "stage": "public_listing_inference",
                "query_used": query,
                "status": "ok",
                "category_count": len(inferred_categories),
            }
        )
        self._append_trace(
            stage="category_resolution",
            phase="completed",
            message="Categorias inferidas desde titulos del listado publico.",
            details={"query_used": query, "categories": inferred_categories},
        )
        return inferred_categories, notes

    async def _enrich_categories(
        self,
        *,
        account_key: str,
        raw_categories: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not raw_categories:
            return []

        tasks = [
            self._market_research.get_category(account_key, category["category_id"])
            for category in raw_categories
            if category.get("category_id")
        ]
        details = await asyncio.gather(*tasks, return_exceptions=True)

        enriched: list[dict[str, Any]] = []
        for category, detail in zip(raw_categories, details, strict=False):
            category_detail = detail if isinstance(detail, dict) else {}
            path_from_root = (
                category_detail.get("path_from_root")
                if isinstance(category_detail.get("path_from_root"), list)
                else []
            )
            path_names = [
                str(entry.get("name") or "").strip()
                for entry in path_from_root
                if isinstance(entry, dict) and str(entry.get("name") or "").strip()
            ]
            category_name = (
                _string_or_none(category_detail.get("name"))
                or _string_or_none(category.get("category_name"))
                or str(category.get("category_id"))
            )
            category_norm = _normalize_phrase(category_name)
            enriched.append(
                {
                    **category,
                    "category_name": category_name,
                    "category_path": path_names,
                    "category_depth": len(path_names),
                    "children_categories": _child_categories_from_detail(category_detail),
                    "total_items_in_this_category": _safe_int(category_detail.get("total_items_in_this_category")),
                    "is_low_signal_category": category_norm in LOW_SIGNAL_CATEGORY_NAMES,
                }
            )
        return enriched

    async def _build_candidate_pool(
        self,
        *,
        account_key: str,
        site_id: str,
        query: str,
        categories: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        self._append_trace(
            stage="candidate_pool",
            phase="started",
            message="Construyendo pool de candidatos.",
            details={"query": query, "categories": categories},
        )
        if not categories:
            return await self._build_query_only_candidate_pool(
                account_key=account_key,
                site_id=site_id,
                query=query,
            )

        discarded: list[dict[str, Any]] = []
        contexts: list[dict[str, Any]] = []
        candidate_pool: list[dict[str, Any]] = []

        for category in categories[:3]:
            category_id = str(category.get("category_id") or "").strip()
            if not category_id:
                continue

            trend_keywords: list[str] = []
            try:
                trends = await self._market_research.get_trends(
                    account_key,
                    site_id=site_id,
                    category_id=category_id,
                )
                trend_keywords = _dedupe_preserving_order(
                    [
                        str(entry.get("keyword") or entry.get("query") or entry.get("name") or "").strip()
                        for entry in trends
                        if isinstance(entry, dict)
                    ]
                )[:10]
            except MercadoLibreAPIError as exc:
                discarded.append(
                    {
                        "keyword": None,
                        "category_id": category_id,
                        "category_name": category.get("category_name"),
                        "reason": f"No se pudieron consultar tendencias de la categoria ({exc.message}).",
                    }
                )

            sample_titles: list[str] = []
            try:
                payload = await self._market_research.search_items(
                    account_key,
                    site_id=site_id,
                    query=query,
                    category_id=category_id,
                    limit=20,
                )
                results = payload.get("results") if isinstance(payload, dict) else []
                sample_titles = _dedupe_preserving_order(
                    [
                        str(item.get("title") or "").strip()
                        for item in results
                        if isinstance(item, dict) and str(item.get("title") or "").strip()
                    ]
                )[:12]
            except MercadoLibreAPIError as exc:
                discarded.append(
                    {
                        "keyword": query,
                        "category_id": category_id,
                        "category_name": category.get("category_name"),
                        "reason": f"No se pudo leer una muestra de publicaciones para la categoria ({exc.message}).",
                    }
                )

            if not sample_titles:
                for public_query in self._category_context_queries(query=query, category=category):
                    public_titles, _, public_error = await self._get_public_listing_titles(
                        site_id=site_id,
                        query=public_query,
                        stage="candidate_pool",
                        trace_context={
                            "category_id": category_id,
                            "category_name": category.get("category_name"),
                        },
                        limit=18,
                    )
                    if public_titles:
                        sample_titles = public_titles[:12]
                        break
                    if public_error:
                        discarded.append(
                            {
                                "keyword": public_query,
                                "category_id": category_id,
                                "category_name": category.get("category_name"),
                                "reason": f"No se pudo leer una muestra publica para la categoria ({public_error}).",
                            }
                        )

            child_categories = category.get("children_categories") if isinstance(category.get("children_categories"), list) else []
            child_names = _dedupe_preserving_order(
                [str(entry.get("name") or "").strip() for entry in child_categories if isinstance(entry, dict)]
            )[:8]
            title_candidates = _dedupe_preserving_order(
                [
                    _clean_title_signal(title, query=query, category_name=category.get("category_name"))
                    for title in sample_titles
                ]
            )[:6]

            contexts.append(
                {
                    "category_id": category_id,
                    "category_name": category.get("category_name"),
                    "category_path": category.get("category_path", []),
                    "child_categories": child_names,
                    "trend_keywords": trend_keywords,
                    "sample_titles": sample_titles,
                }
            )
            self._append_trace(
                stage="candidate_pool",
                phase="info",
                message="Contexto de categoria recopilado para expansion.",
                details=contexts[-1],
            )

            candidate_pool.extend(
                [
                    {
                        "query": candidate_query,
                        "source": source,
                        "source_category_id": category_id,
                        "source_category_name": category.get("category_name"),
                    }
                    for source, values in (
                        ("trend", trend_keywords),
                        ("child_category", child_names),
                        ("search_title", title_candidates),
                    )
                    for candidate_query in values
                    if candidate_query
                ]
            )

        ai_candidates = await self._expand_candidates_with_ai(
            query=query,
            contexts=contexts,
            public_titles=[
                title
                for context in contexts
                for title in (context.get("sample_titles") or [])[:6]
            ],
        )
        candidate_pool.extend(
            [
                {
                    "query": candidate_query,
                    "source": "ai_expansion",
                    "source_category_id": None,
                    "source_category_name": None,
                }
                for candidate_query in ai_candidates
            ]
        )

        deduped_pool: list[dict[str, Any]] = []
        seen_queries: set[str] = set()
        for entry in candidate_pool:
            raw_query = str(entry.get("query") or "").strip()
            normalized = _normalize_phrase(raw_query)
            if not raw_query or not normalized or normalized in seen_queries:
                continue
            seen_queries.add(normalized)
            deduped_pool.append(entry)

        self._append_trace(
            stage="candidate_pool",
            phase="completed",
            message="Pool de candidatos construido.",
            details={
                "candidate_count": len(deduped_pool),
                "candidates": deduped_pool,
                "discarded": discarded,
            },
        )
        return deduped_pool[:16], discarded

    async def _expand_candidates_with_ai(
        self,
        *,
        query: str,
        contexts: list[dict[str, Any]],
        site_trends: list[str] | None = None,
        public_titles: list[str] | None = None,
    ) -> list[str]:
        normalized_site_trends = _dedupe_preserving_order(site_trends or [])[:20]
        normalized_public_titles = _dedupe_preserving_order(public_titles or [])[:12]
        if not contexts and not normalized_site_trends and not normalized_public_titles:
            self._append_trace(
                stage="ai_expansion",
                phase="info",
                message="Se omitio la expansion IA porque no habia contexto suficiente.",
            )
            return []

        try:
            llm = self._get_llm()
        except Exception as exc:
            self._append_trace(
                stage="ai_expansion",
                phase="failed",
                message="No se pudo inicializar el modelo para expansion IA.",
                details={"error": str(exc), "exception_type": exc.__class__.__name__},
            )
            return []

        context_lines = [f"Consulta original: {query}", ""]
        if normalized_site_trends:
            context_lines.extend(
                [
                    "Tendencias generales del sitio: " + ", ".join(normalized_site_trends),
                    "",
                ]
            )
        if normalized_public_titles:
            context_lines.extend(
                [
                    "Titulos publicos observados: " + " | ".join(normalized_public_titles[:10]),
                    "",
                ]
            )
        for index, context in enumerate(contexts, start=1):
            context_lines.extend(
                [
                    f"Categoria {index}: {context.get('category_name') or context.get('category_id')}",
                    f"Path: {' / '.join(context.get('category_path') or []) or 'N/D'}",
                    "Subcategorias: " + ", ".join(context.get("child_categories") or []) if context.get("child_categories") else "Subcategorias: ninguna visible",
                    "Tendencias: " + ", ".join(context.get("trend_keywords") or []) if context.get("trend_keywords") else "Tendencias: ninguna visible",
                    "Titulos vistos: " + " | ".join((context.get("sample_titles") or [])[:8]) if context.get("sample_titles") else "Titulos vistos: ninguno",
                    "",
                ]
            )

        messages = [
            SystemMessage(content=CANDIDATE_EXPANSION_PROMPT),
            HumanMessage(content="\n".join(context_lines)),
        ]

        try:
            response = await llm.ainvoke(
                messages,
                config=llm_run_config("market_insights.query_expansion"),
            )
        except Exception as exc:
            self._append_trace(
                stage="ai_expansion",
                phase="failed",
                message="La expansion IA fallo durante la invocacion.",
                details={"error": str(exc), "exception_type": exc.__class__.__name__},
            )
            return []

        raw_text = response.content if isinstance(response.content, str) else str(response.content)
        payload = _extract_json_payload(raw_text)
        queries = payload.get("queries")
        if not isinstance(queries, list):
            self._append_trace(
                stage="ai_expansion",
                phase="failed",
                message="La expansion IA no devolvio JSON valido.",
                details={"raw_text": raw_text},
            )
            return []
        result = _dedupe_preserving_order([str(item or "").strip() for item in queries])[:12]
        self._append_trace(
            stage="ai_expansion",
            phase="completed",
            message="Expansion IA completada.",
            details={
                "queries": result,
                "context_category_count": len(contexts),
                "site_trend_count": len(normalized_site_trends),
                "public_title_count": len(normalized_public_titles),
            },
        )
        return result

    async def _collect_opportunities(
        self,
        *,
        account_key: str,
        site_id: str,
        query: str,
        categories: list[dict[str, Any]],
        limit: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        validated: list[dict[str, Any]] = []
        candidate_pool, discarded = await self._build_candidate_pool(
            account_key=account_key,
            site_id=site_id,
            query=query,
            categories=categories,
        )
        self._append_trace(
            stage="candidate_validation",
            phase="started",
            message="Iniciando validacion de candidatos.",
            details={"candidate_pool_size": len(candidate_pool)},
        )
        seen_keywords: set[str] = set()

        evaluations = await asyncio.gather(
            *[
                self._evaluate_candidate(
                    account_key=account_key,
                    site_id=site_id,
                    query=query,
                    categories=categories,
                    candidate_entry=entry,
                    rank=index,
                )
                for index, entry in enumerate(candidate_pool, start=1)
            ],
            return_exceptions=True,
        )

        for candidate_entry, evaluation in zip(candidate_pool, evaluations, strict=False):
            if isinstance(evaluation, Exception):
                discarded.append(
                    {
                        "keyword": candidate_entry.get("query"),
                        "category_id": candidate_entry.get("source_category_id"),
                        "category_name": candidate_entry.get("source_category_name"),
                        "reason": f"Fallo la validacion de una tendencia ({evaluation.__class__.__name__}: {str(evaluation) or 'sin detalle'}).",
                    }
                )
                self._append_trace(
                    stage="candidate_validation",
                    phase="failed",
                    message="Un candidato fallo con excepcion durante la validacion.",
                    details={
                        "candidate": candidate_entry,
                        "exception_type": evaluation.__class__.__name__,
                        "error": str(evaluation) or "sin detalle",
                    },
                )
                continue
            keyword_norm = _normalize_phrase(evaluation.get("keyword"))
            if keyword_norm and keyword_norm in seen_keywords:
                continue
            if evaluation.get("accepted"):
                if keyword_norm:
                    seen_keywords.add(keyword_norm)
                validated.append(evaluation["opportunity"])
                self._append_trace(
                    stage="candidate_validation",
                    phase="completed",
                    message="Candidato validado como oportunidad.",
                    details=evaluation["opportunity"],
                )
            else:
                discarded.append(
                    {
                        "keyword": evaluation.get("keyword"),
                        "category_id": evaluation.get("category_id"),
                        "category_name": evaluation.get("category_name"),
                        "reason": evaluation.get("reason"),
                    }
                )
                self._append_trace(
                    stage="candidate_validation",
                    phase="info",
                    message="Candidato descartado.",
                    details=evaluation,
                )

        validated.sort(key=lambda entry: entry.get("ranking_score", 0.0), reverse=True)
        self._append_trace(
            stage="candidate_validation",
            phase="completed",
            message="Finalizo la validacion de candidatos.",
            details={
                "validated_count": len(validated),
                "discarded_count": len(discarded),
            },
        )
        return validated[: max(limit * 2, limit)], discarded

    async def _evaluate_candidate(
        self,
        *,
        account_key: str,
        site_id: str,
        query: str,
        categories: list[dict[str, Any]],
        candidate_entry: dict[str, Any],
        rank: int,
    ) -> dict[str, Any]:
        keyword = _string_or_none(candidate_entry.get("query"))
        if not keyword:
            return {"accepted": False, "keyword": None, "reason": "La tendencia no incluyo una keyword util."}

        category = self._find_candidate_category_context(keyword=keyword, categories=categories, candidate_entry=candidate_entry)
        predicted_category_id, predicted_category_name, predicted_attributes = await self._predict_candidate_category(
            account_key=account_key,
            site_id=site_id,
            keyword=keyword,
        )
        if self._is_attribute_only_candidate(
            keyword=keyword,
            query=query,
            predicted_attributes=predicted_attributes,
        ):
            return {
                "accepted": False,
                "keyword": keyword,
                "category_id": predicted_category_id or category.get("category_id"),
                "category_name": predicted_category_name or category.get("category_name"),
                "reason": "La keyword se apoya demasiado en marca, color o personaje y no en un producto suficientemente diferencial.",
            }

        specificity_score, specificity_reason = self._score_specificity(
            keyword=keyword,
            query=query,
            category=category,
        )
        if specificity_score < 1.2:
            return {
                "accepted": False,
                "keyword": keyword,
                "category_id": predicted_category_id or category.get("category_id"),
                "category_name": predicted_category_name or category.get("category_name"),
                "reason": specificity_reason,
            }

        search_payload, search_scope = await self._search_with_validation(
            account_key=account_key,
            site_id=site_id,
            keyword=keyword,
            category_id=predicted_category_id or str(category.get("category_id") or "").strip() or None,
            category_name=predicted_category_name or category.get("category_name"),
        )
        summary = self._summarize_search_payload(keyword=keyword, payload=search_payload)
        evidence_score = self._score_evidence(summary=summary, rank=rank, search_scope=search_scope)

        if summary["sample_result_count"] < 3:
            return {
                "accepted": False,
                "keyword": keyword,
                "category_id": predicted_category_id or category.get("category_id"),
                "category_name": predicted_category_name or category.get("category_name"),
                "reason": "La busqueda devolvio una muestra demasiado chica para validar la oportunidad.",
            }
        if summary["matching_title_count"] < 1:
            return {
                "accepted": False,
                "keyword": keyword,
                "category_id": predicted_category_id or category.get("category_id"),
                "category_name": predicted_category_name or category.get("category_name"),
                "reason": "No hubo coincidencias claras en los titulos de la muestra de Mercado Libre.",
            }
        if evidence_score < 2.8:
            return {
                "accepted": False,
                "keyword": keyword,
                "category_id": predicted_category_id or category.get("category_id"),
                "category_name": predicted_category_name or category.get("category_name"),
                "reason": "La senal observable de mercado quedo demasiado debil para recomendarla con confianza.",
            }

        trend_bucket = _trend_bucket(rank)
        ranking_score = round(evidence_score + specificity_score, 2)
        return {
            "accepted": True,
            "keyword": keyword,
            "opportunity": {
                "keyword": keyword,
                "category_id": predicted_category_id or category.get("category_id"),
                "category_name": predicted_category_name or category.get("category_name"),
                "category_path": category.get("category_path", []),
                "trend_bucket": trend_bucket["label"],
                "trend_rank": rank,
                "validation_status": "validated",
                "specificity_score": round(specificity_score, 2),
                "evidence_score": round(evidence_score, 2),
                "ranking_score": ranking_score,
                "justification": self._build_justification(
                    keyword=keyword,
                    category=category,
                    summary=summary,
                    trend_bucket=trend_bucket["label"],
                ),
                "risk_flags": self._build_risk_flags(summary=summary, category=category),
                "market_evidence": {
                    "search_scope": search_scope,
                    "total_results": summary["total_results"],
                    "sample_result_count": summary["sample_result_count"],
                    "matching_title_count": summary["matching_title_count"],
                    "price_stats": summary["price_stats"],
                    "avg_sold_quantity": summary["avg_sold_quantity"],
                    "sample_titles": summary["sample_titles"][:3],
                    "sample_results": summary["sample_results"][:3],
                },
            },
        }

    def _find_candidate_category_context(
        self,
        *,
        keyword: str,
        categories: list[dict[str, Any]],
        candidate_entry: dict[str, Any],
    ) -> dict[str, Any]:
        hinted_category_id = str(candidate_entry.get("source_category_id") or "").strip()
        if hinted_category_id:
            hinted = next(
                (category for category in categories if str(category.get("category_id") or "").strip() == hinted_category_id),
                None,
            )
            if hinted is not None:
                return hinted

        keyword_tokens = set(_meaningful_tokens(keyword))
        best_category = categories[0] if categories else {}
        best_score = -1
        for category in categories:
            score = 0
            score += len(keyword_tokens & set(_meaningful_tokens(category.get("category_name"))))
            for child in category.get("children_categories") or []:
                if not isinstance(child, dict):
                    continue
                child_name = str(child.get("name") or "").strip()
                if _normalize_phrase(child_name) == _normalize_phrase(keyword):
                    score += 3
                score += len(keyword_tokens & set(_meaningful_tokens(child_name)))
            if score > best_score:
                best_score = score
                best_category = category
        return best_category

    async def _predict_candidate_category(
        self,
        *,
        account_key: str,
        site_id: str,
        keyword: str,
    ) -> tuple[str | None, str | None, list[dict[str, Any]]]:
        try:
            suggestions = await self._market_research.predict_category(
                account_key,
                site_id=site_id,
                query=keyword,
                limit=3,
            )
        except MercadoLibreAPIError as exc:
            self._append_trace(
                stage="candidate_category_prediction",
                phase="failed",
                message="Fallo la prediccion de categoria para un candidato.",
                details={"keyword": keyword, "error": exc.message},
            )
            return None, None, []

        if not suggestions:
            self._append_trace(
                stage="candidate_category_prediction",
                phase="info",
                message="No hubo categoria sugerida para un candidato.",
                details={"keyword": keyword},
            )
            return None, None, []

        top = suggestions[0] if isinstance(suggestions[0], dict) else {}
        self._append_trace(
            stage="candidate_category_prediction",
            phase="completed",
            message="Se predijo categoria para un candidato.",
            details={"keyword": keyword, "suggestions": suggestions[:3]},
        )
        top_attributes = top.get("attributes") if isinstance(top.get("attributes"), list) else []
        return (
            _string_or_none(top.get("category_id")),
            _string_or_none(top.get("category_name")),
            [attribute for attribute in top_attributes if isinstance(attribute, dict)],
        )

    async def _search_with_validation(
        self,
        *,
        account_key: str,
        site_id: str,
        keyword: str,
        category_id: str | None,
        category_name: str | None,
    ) -> tuple[dict[str, Any], str]:
        if category_id:
            try:
                category_payload = await self._market_research.search_items(
                    account_key,
                    site_id=site_id,
                    query=keyword,
                    category_id=category_id,
                    limit=12,
                )
                category_results = category_payload.get("results") if isinstance(category_payload, dict) else []
                if isinstance(category_results, list) and category_results:
                    self._append_trace(
                        stage="search_validation",
                        phase="completed",
                        message="Validacion resuelta con busqueda por categoria.",
                        details={
                            "keyword": keyword,
                            "category_id": category_id,
                            "scope": "category",
                            "result_count": len(category_results),
                            "total_results": category_payload.get("paging", {}).get("total")
                            if isinstance(category_payload.get("paging"), dict)
                            else None,
                        },
                    )
                    return category_payload, "category"
            except MercadoLibreAPIError as exc:
                self._append_trace(
                    stage="search_validation",
                    phase="failed",
                    message="Fallo la busqueda por categoria durante la validacion.",
                    details={"keyword": keyword, "category_id": category_id, "error": exc.message},
                )
                pass

        try:
            site_payload = await self._market_research.search_items(
                account_key,
                site_id=site_id,
                query=keyword,
                category_id=None,
                limit=12,
            )
            site_results = site_payload.get("results") if isinstance(site_payload, dict) else []
            if isinstance(site_results, list) and site_results:
                self._append_trace(
                    stage="search_validation",
                    phase="completed",
                    message="Validacion resuelta con busqueda a nivel sitio.",
                    details={
                        "keyword": keyword,
                        "scope": "site",
                        "result_count": len(site_results),
                        "total_results": site_payload.get("paging", {}).get("total")
                        if isinstance(site_payload.get("paging"), dict)
                        else None,
                    },
                )
                return site_payload if isinstance(site_payload, dict) else {}, "site"
        except MercadoLibreAPIError as exc:
            self._append_trace(
                stage="search_validation",
                phase="failed",
                message="Fallo la busqueda a nivel sitio durante la validacion.",
                details={"keyword": keyword, "error": exc.message},
            )

        public_titles, public_payload, public_error = await self._get_public_listing_titles(
            site_id=site_id,
            query=keyword,
            stage="search_validation",
            trace_context={"keyword": keyword, "scope": "web_listing"},
            limit=12,
        )
        if public_titles and isinstance(public_payload, dict):
            self._append_trace(
                stage="search_validation",
                phase="completed",
                message="Validacion resuelta con listado publico por keyword.",
                details={"keyword": keyword, "scope": "web_listing", "result_count": len(public_titles)},
            )
            return public_payload, "web_listing"

        if category_name:
            public_titles, public_payload, public_error = await self._get_public_listing_titles(
                site_id=site_id,
                query=category_name,
                stage="search_validation",
                trace_context={"keyword": keyword, "scope": "web_category_listing", "category_name": category_name},
                limit=12,
            )
            if public_titles and isinstance(public_payload, dict):
                self._append_trace(
                    stage="search_validation",
                    phase="completed",
                    message="Validacion resuelta con listado publico de categoria.",
                    details={
                        "keyword": keyword,
                        "scope": "web_category_listing",
                        "category_name": category_name,
                        "result_count": len(public_titles),
                    },
                )
                return public_payload, "web_category_listing"

        raise MercadoLibreAPIError(
            message=public_error or "No se pudo validar la oportunidad con ninguna fuente observable.",
            status_code=403,
            code="market_validation_search_failed",
            details={"keyword": keyword, "category_id": category_id, "category_name": category_name},
        )

    def _score_specificity(
        self,
        *,
        keyword: str,
        query: str,
        category: dict[str, Any],
    ) -> tuple[float, str]:
        keyword_norm = _normalize_phrase(keyword)
        query_norm = _normalize_phrase(query)
        category_names = [category.get("category_name"), *(category.get("category_path") or [])]
        category_norms = {_normalize_phrase(name) for name in category_names if name}
        tokens = _meaningful_tokens(keyword)

        score = 1.4 + max(0.0, 0.45 * (len(tokens) - 1))
        if keyword_norm == query_norm:
            score -= 1.8
        if keyword_norm in category_norms:
            score -= 1.5
        if len(tokens) == 1 and tokens[0] in VERY_GENERIC_KEYWORDS:
            score -= 1.4
        for token in tokens:
            if token in VERY_GENERIC_KEYWORDS:
                score -= 0.45
        if category.get("is_low_signal_category"):
            score -= 0.2

        if score < 1.2:
            reason = "La keyword quedo demasiado cerca de una categoria amplia o generica."
        else:
            reason = ""
        return score, reason

    def _summarize_search_payload(
        self,
        *,
        keyword: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        results = payload.get("results") if isinstance(payload, dict) else []
        items = [item for item in results if isinstance(item, dict)]
        sold_quantities = [_safe_int(item.get("sold_quantity")) for item in items]
        valid_sold_quantities = [value for value in sold_quantities if value is not None]
        sample_titles = [str(item.get("title") or "").strip() for item in items if str(item.get("title") or "").strip()]
        matching_titles = [title for title in sample_titles if _title_matches_keyword(title, keyword)]

        sample_results = [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "price": item.get("price"),
                "currency_id": item.get("currency_id"),
                "sold_quantity": item.get("sold_quantity"),
                "permalink": item.get("permalink"),
            }
            for item in items[:5]
        ]

        return {
            "total_results": payload.get("paging", {}).get("total") if isinstance(payload.get("paging"), dict) else None,
            "sample_result_count": len(items),
            "matching_title_count": len(matching_titles),
            "sample_titles": sample_titles,
            "sample_results": sample_results,
            "price_stats": _price_stats(items),
            "avg_sold_quantity": round(fmean(valid_sold_quantities), 2) if valid_sold_quantities else None,
        }

    def _score_evidence(
        self,
        *,
        summary: dict[str, Any],
        rank: int,
        search_scope: str,
    ) -> float:
        score = 0.0
        total_results = _safe_int(summary.get("total_results")) or 0
        sample_count = int(summary.get("sample_result_count") or 0)
        matching_count = int(summary.get("matching_title_count") or 0)
        avg_sold_quantity = _safe_float(summary.get("avg_sold_quantity")) or 0.0
        price_stats = summary.get("price_stats") if isinstance(summary.get("price_stats"), dict) else {}
        trend_bucket = _trend_bucket(rank)

        if sample_count >= 3:
            score += 1.0
        if total_results >= 25:
            score += 1.0
        if matching_count >= 1:
            score += 1.2
        if avg_sold_quantity >= 1:
            score += 0.8
        if price_stats:
            score += 0.3
        if search_scope in {"web_listing", "web_category_listing"} and sample_count >= 6:
            score += 0.8
        if search_scope == "web_listing" and matching_count >= 2:
            score += 0.4

        score += {
            "fast_growth": 0.7,
            "most_wanted": 0.4,
            "popular": 0.2,
        }[trend_bucket["id"]]

        if search_scope in {"site", "web_listing"}:
            score -= 0.2

        return round(score, 2)

    def _build_justification(
        self,
        *,
        keyword: str,
        category: dict[str, Any],
        summary: dict[str, Any],
        trend_bucket: str,
    ) -> str:
        parts = [
            f"Aparece como tendencia {trend_bucket} en {category.get('category_name') or 'la categoria resuelta'}.",
        ]
        total_results = _safe_int(summary.get("total_results"))
        if total_results:
            parts.append(f"La busqueda visible muestra al menos {total_results} resultados para '{keyword}'.")
        if summary.get("matching_title_count"):
            parts.append(
                f"Se encontraron {summary['matching_title_count']} coincidencias claras en titulos de la muestra."
            )
        avg_sold_quantity = _safe_float(summary.get("avg_sold_quantity"))
        if avg_sold_quantity is not None:
            parts.append(f"La venta promedio visible en la muestra es de {avg_sold_quantity:.2f} unidades.")
        price_stats = summary.get("price_stats") if isinstance(summary.get("price_stats"), dict) else {}
        if price_stats:
            parts.append(
                "El rango de precios observado va de "
                f"{price_stats['min']} a {price_stats['max']}."
            )
        return " ".join(parts)

    def _build_risk_flags(
        self,
        *,
        summary: dict[str, Any],
        category: dict[str, Any],
    ) -> list[str]:
        risks: list[str] = []
        total_results = _safe_int(summary.get("total_results")) or 0
        avg_sold_quantity = _safe_float(summary.get("avg_sold_quantity"))
        price_stats = summary.get("price_stats") if isinstance(summary.get("price_stats"), dict) else {}

        if total_results >= 500:
            risks.append("Competencia alta en la busqueda visible")
        if avg_sold_quantity is None or avg_sold_quantity < 1:
            risks.append("La demanda visible en la muestra es limitada")
        if price_stats:
            min_price = _safe_float(price_stats.get("min")) or 0.0
            max_price = _safe_float(price_stats.get("max")) or 0.0
            if min_price > 0 and max_price / min_price >= 3:
                risks.append("Rango de precios muy disperso")
        if category.get("resolved_by") == "search_fallback":
            risks.append("La categoria fue inferida por busqueda y no por predictor directo")
        return risks[:3]
