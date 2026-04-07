from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.adapters.market_research import MarketResearchAdapter
from app.agents.listing_doctor_nodes import (
    build_action_plan_node,
    build_attribute_benchmark_node,
    build_batch_fetch_competitor_details_node,
    build_collect_candidates_node,
    build_competitiveness_scoring_node,
    build_compute_competitor_signals_node,
    build_copywriter_context_node,
    build_dedupe_candidates_node,
    build_dedupe_queries_node,
    build_description_benchmark_node,
    build_detect_quick_wins_node,
    build_detect_structural_gaps_node,
    build_detailed_diagnosis_node,
    build_executive_summary_node,
    build_expand_market_queries_node,
    build_extract_competitor_features_node,
    build_extract_product_signals_node,
    build_load_listing_context_node,
    build_normalize_listing_node,
    build_price_benchmark_node,
    build_prioritize_actions_node,
    build_result_node,
    build_search_marketplace_node,
    build_seed_queries_node,
    build_shortlist_candidates_node,
    build_suggest_description_with_existing_copywriter_node,
    build_suggest_titles_with_existing_copywriter_node,
    build_title_benchmark_node,
)
from app.agents.listing_doctor_state import ListingDoctorState
from app.services.copywriter import CopywriterService
from app.services.items import ItemsService


TRACE_TEXT_LIMIT = 240
TRACE_COLLECTION_SAMPLE = 3


def _truncate_text(value: str, *, limit: int = TRACE_TEXT_LIMIT) -> str:
    collapsed = " ".join(str(value or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: max(0, limit - 3)].rstrip()}..."


def _summarize_sequence(values: Sequence[Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"count": len(values)}
    sample = list(values[:TRACE_COLLECTION_SAMPLE])
    if not sample:
        return summary
    if all(isinstance(item, dict) for item in sample):
        compact_sample: list[dict[str, Any]] = []
        for item in sample:
            compact_sample.append(
                {
                    key: item.get(key)
                    for key in (
                        "item_id",
                        "id",
                        "title",
                        "query",
                        "status",
                        "price",
                        "benchmark_score",
                        "message",
                        "label",
                    )
                    if item.get(key) not in (None, "", [])
                }
            )
        summary["sample"] = compact_sample
        return summary
    summary["sample"] = [
        _truncate_text(item) if isinstance(item, str) else item
        for item in sample
    ]
    return summary


def _summarize_value(value: Any, *, depth: int = 0) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_text(value)
    if depth >= 2:
        if isinstance(value, dict):
            return {"keys": list(value.keys())[:8], "count": len(value)}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return {"count": len(value)}
        return _truncate_text(value)
    if isinstance(value, dict):
        preferred_keys = [
            "item_id",
            "title",
            "category_name",
            "brand",
            "product_type",
            "search_queries",
            "seed_queries",
            "query_count",
            "total_candidates",
            "shortlisted_competitors",
            "median_price",
            "scores",
            "strengths",
            "weaknesses",
            "warnings",
            "factual_points",
            "proxy_points",
            "uncertainties",
            "suggested_titles",
            "positioning_strategy",
        ]
        ordered_keys = [key for key in preferred_keys if key in value]
        ordered_keys.extend(key for key in value.keys() if key not in ordered_keys)
        summarized: dict[str, Any] = {}
        for key in ordered_keys[:10]:
            summarized[key] = _summarize_value(value.get(key), depth=depth + 1)
        if len(value) > 10:
            summarized["_remaining_keys"] = len(value) - 10
        return summarized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _summarize_sequence(list(value))
    return _truncate_text(value)


def _state_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    interesting_keys = [
        "listing",
        "normalized_listing",
        "product_signals",
        "query_bundle",
        "search_runs",
        "candidates",
        "shortlisted_candidates",
        "competitor_features",
        "market_summary",
        "scores",
        "findings",
        "actions",
        "ai_suggestions",
        "warnings",
    ]
    snapshot: dict[str, Any] = {}
    for key in interesting_keys:
        if key not in state:
            continue
        snapshot[key] = _summarize_value(state.get(key))
    return snapshot


async def _emit_trace(
    state: dict[str, Any],
    *,
    agent: str,
    node: str,
    phase: str,
    message: str,
    details: Any | None = None,
) -> None:
    hook = state.get("trace_hook")
    if hook is None:
        return
    await hook(agent, node, phase, message, details)


def _wrap_node(agent_name: str, node_name: str, node: Any):
    async def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        await _emit_trace(
            state,
            agent=agent_name,
            node=node_name,
            phase="started",
            message=f"Iniciando nodo {node_name}.",
            details={"state_before": _state_snapshot(state)},
        )
        try:
            result = await node(state)
            await _emit_trace(
                state,
                agent=agent_name,
                node=node_name,
                phase="completed",
                message=f"Nodo {node_name} completado.",
                details={
                    "returned_keys": list(result.keys()) if isinstance(result, dict) else [],
                    "result_preview": _summarize_value(result),
                },
            )
            return result
        except Exception as exc:
            await _emit_trace(
                state,
                agent=agent_name,
                node=node_name,
                phase="failed",
                message=f"Nodo {node_name} fallo.",
                details={
                    "error": _truncate_text(str(exc)),
                    "exception_type": exc.__class__.__name__,
                    "state_before": _state_snapshot(state),
                },
            )
            raise

    return wrapped


def _wrap_graph(agent_name: str, graph: Any):
    async def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        await _emit_trace(
            state,
            agent=agent_name,
            node=agent_name,
            phase="started",
            message=f"Iniciando subworkflow {agent_name}.",
            details={"state_before": _state_snapshot(state)},
        )
        try:
            result = await graph.ainvoke(state)
            await _emit_trace(
                state,
                agent=agent_name,
                node=agent_name,
                phase="completed",
                message=f"Subworkflow {agent_name} completado.",
                details={"state_after": _state_snapshot(result)},
            )
            return result
        except Exception as exc:
            await _emit_trace(
                state,
                agent=agent_name,
                node=agent_name,
                phase="failed",
                message=f"Subworkflow {agent_name} fallo.",
                details={
                    "error": _truncate_text(str(exc)),
                    "exception_type": exc.__class__.__name__,
                },
            )
            raise

    return wrapped


def _compile_linear_subgraph(nodes: Sequence[tuple[str, Any]]):
    builder = StateGraph(ListingDoctorState)
    if not nodes:
        return builder.compile()

    first_name = nodes[0][0]
    builder.add_edge(START, first_name)

    previous_name = None
    for name, node in nodes:
        builder.add_node(name, node)
        if previous_name is not None:
            builder.add_edge(previous_name, name)
        previous_name = name

    builder.add_edge(nodes[-1][0], END)
    return builder.compile()


def build_listing_doctor_graph(
    *,
    llm: Any,
    market_research: MarketResearchAdapter,
    items_service: ItemsService,
    copywriter_service: CopywriterService,
):
    intake_agent_name = "listing_intake_agent"
    query_agent_name = "query_strategy_agent"
    discovery_agent_name = "competitor_discovery_agent"
    enrichment_agent_name = "competitor_enrichment_agent"
    benchmark_agent_name = "benchmark_analysis_agent"
    opportunity_agent_name = "opportunity_agent"
    synthesis_agent_name = "strategy_synthesis_agent"
    copywriter_agent_name = "copywriter_enhancement_agent"

    listing_intake_graph = _compile_linear_subgraph(
        [
            ("load_listing_context", _wrap_node(intake_agent_name, "load_listing_context", build_load_listing_context_node(items_service=items_service, market_research=market_research))),
            ("normalize_listing", _wrap_node(intake_agent_name, "normalize_listing", build_normalize_listing_node(llm=llm))),
            ("extract_product_signals", _wrap_node(intake_agent_name, "extract_product_signals", build_extract_product_signals_node())),
        ]
    )

    query_strategy_graph = _compile_linear_subgraph(
        [
            ("build_seed_queries", _wrap_node(query_agent_name, "build_seed_queries", build_seed_queries_node())),
            ("expand_market_queries", _wrap_node(query_agent_name, "expand_market_queries", build_expand_market_queries_node(llm=llm, market_research=market_research))),
            ("dedupe_queries", _wrap_node(query_agent_name, "dedupe_queries", build_dedupe_queries_node())),
        ]
    )

    competitor_discovery_graph = _compile_linear_subgraph(
        [
            ("search_marketplace", _wrap_node(discovery_agent_name, "search_marketplace", build_search_marketplace_node(market_research=market_research))),
            ("collect_candidates", _wrap_node(discovery_agent_name, "collect_candidates", build_collect_candidates_node())),
            ("dedupe_candidates", _wrap_node(discovery_agent_name, "dedupe_candidates", build_dedupe_candidates_node())),
            ("shortlist_candidates", _wrap_node(discovery_agent_name, "shortlist_candidates", build_shortlist_candidates_node())),
        ]
    )

    competitor_enrichment_graph = _compile_linear_subgraph(
        [
            ("batch_fetch_competitor_details", _wrap_node(enrichment_agent_name, "batch_fetch_competitor_details", build_batch_fetch_competitor_details_node(market_research=market_research))),
            ("extract_competitor_features", _wrap_node(enrichment_agent_name, "extract_competitor_features", build_extract_competitor_features_node())),
            ("compute_competitor_signals", _wrap_node(enrichment_agent_name, "compute_competitor_signals", build_compute_competitor_signals_node())),
        ]
    )

    benchmark_graph = _compile_linear_subgraph(
        [
            ("price_benchmark", _wrap_node(benchmark_agent_name, "price_benchmark", build_price_benchmark_node())),
            ("title_benchmark", _wrap_node(benchmark_agent_name, "title_benchmark", build_title_benchmark_node())),
            ("attribute_benchmark", _wrap_node(benchmark_agent_name, "attribute_benchmark", build_attribute_benchmark_node())),
            ("description_benchmark", _wrap_node(benchmark_agent_name, "description_benchmark", build_description_benchmark_node())),
            ("competitiveness_scoring", _wrap_node(benchmark_agent_name, "competitiveness_scoring", build_competitiveness_scoring_node())),
        ]
    )

    opportunity_graph = _compile_linear_subgraph(
        [
            ("detect_quick_wins", _wrap_node(opportunity_agent_name, "detect_quick_wins", build_detect_quick_wins_node())),
            ("detect_structural_gaps", _wrap_node(opportunity_agent_name, "detect_structural_gaps", build_detect_structural_gaps_node())),
            ("prioritize_actions", _wrap_node(opportunity_agent_name, "prioritize_actions", build_prioritize_actions_node())),
        ]
    )

    synthesis_graph = _compile_linear_subgraph(
        [
            ("build_executive_summary", _wrap_node(synthesis_agent_name, "build_executive_summary", build_executive_summary_node(llm=llm))),
            ("build_detailed_diagnosis", _wrap_node(synthesis_agent_name, "build_detailed_diagnosis", build_detailed_diagnosis_node(llm=llm))),
            ("build_action_plan", _wrap_node(synthesis_agent_name, "build_action_plan", build_action_plan_node(llm=llm))),
        ]
    )

    copywriter_graph = _compile_linear_subgraph(
        [
            ("build_copywriter_context", _wrap_node(copywriter_agent_name, "build_copywriter_context", build_copywriter_context_node())),
            ("suggest_titles_with_existing_copywriter", _wrap_node(copywriter_agent_name, "suggest_titles_with_existing_copywriter", build_suggest_titles_with_existing_copywriter_node(copywriter_service=copywriter_service))),
            ("suggest_description_with_existing_copywriter", _wrap_node(copywriter_agent_name, "suggest_description_with_existing_copywriter", build_suggest_description_with_existing_copywriter_node(copywriter_service=copywriter_service))),
        ]
    )

    builder = StateGraph(ListingDoctorState)
    builder.add_node(intake_agent_name, _wrap_graph(intake_agent_name, listing_intake_graph))
    builder.add_node(query_agent_name, _wrap_graph(query_agent_name, query_strategy_graph))
    builder.add_node(discovery_agent_name, _wrap_graph(discovery_agent_name, competitor_discovery_graph))
    builder.add_node(enrichment_agent_name, _wrap_graph(enrichment_agent_name, competitor_enrichment_graph))
    builder.add_node(benchmark_agent_name, _wrap_graph(benchmark_agent_name, benchmark_graph))
    builder.add_node(opportunity_agent_name, _wrap_graph(opportunity_agent_name, opportunity_graph))
    builder.add_node(synthesis_agent_name, _wrap_graph(synthesis_agent_name, synthesis_graph))
    builder.add_node(copywriter_agent_name, _wrap_graph(copywriter_agent_name, copywriter_graph))
    builder.add_node("build_result", _wrap_node("service", "build_result", build_result_node()))

    builder.add_edge(START, intake_agent_name)
    builder.add_edge(intake_agent_name, query_agent_name)
    builder.add_edge(query_agent_name, discovery_agent_name)
    builder.add_edge(discovery_agent_name, enrichment_agent_name)
    builder.add_edge(enrichment_agent_name, benchmark_agent_name)
    builder.add_edge(benchmark_agent_name, opportunity_agent_name)
    builder.add_edge(opportunity_agent_name, synthesis_agent_name)
    builder.add_edge(synthesis_agent_name, copywriter_agent_name)
    builder.add_edge(copywriter_agent_name, "build_result")
    builder.add_edge("build_result", END)

    return builder.compile()
