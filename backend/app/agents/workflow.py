from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from app.agents.memory import JsonAgentMemoryStore
from app.agents.nodes import (
    build_account_dispatch_node,
    build_clarification_node,
    build_finalize_specialist_node,
    build_intent_analyst_node,
    build_market_dispatch_node,
    build_memory_recall_node,
    build_memory_writer_node,
    build_prepare_specialist_context_node,
    build_route_guard_node,
    build_tool_reasoner_node,
    specialist_tools_route,
)
from app.agents.state import BusinessAssistantState, SpecializedAgentState


def _route_after_guard(state: BusinessAssistantState) -> str:
    return state.get("route", "clarification")


def build_specialist_graph(
    *,
    specialist: str,
    llm,
    tools,
    tooling_summary: str,
):
    bound_model = llm.bind_tools(tools)
    builder = StateGraph(SpecializedAgentState)

    prepare_node_name = f"{specialist}_prepare"
    reasoner_node_name = f"{specialist}_reasoner"
    tools_node_name = f"{specialist}_tools"
    finalize_node_name = f"{specialist}_finalize"

    builder.add_node(
        prepare_node_name,
        build_prepare_specialist_context_node(
            specialist=specialist,
            tooling_summary=tooling_summary,
        ),
    )
    builder.add_node(
        reasoner_node_name,
        build_tool_reasoner_node(bound_model, llm, specialist=specialist),
    )
    builder.add_node(tools_node_name, ToolNode(tools))
    builder.add_node(finalize_node_name, build_finalize_specialist_node())

    builder.add_edge(START, prepare_node_name)
    builder.add_edge(prepare_node_name, reasoner_node_name)
    builder.add_conditional_edges(
        reasoner_node_name,
        specialist_tools_route,
        {
            "tools": tools_node_name,
            "finalize": finalize_node_name,
        },
    )
    builder.add_edge(tools_node_name, reasoner_node_name)
    builder.add_edge(finalize_node_name, END)

    return builder.compile()


async def build_business_assistant_graph(
    *,
    router_llm,
    worker_llm,
    memory_store: JsonAgentMemoryStore,
    toolbox,
    history_window: int,
):
    account_tools = await toolbox.get_account_tools()
    market_tools = await toolbox.get_market_tools()

    account_graph = build_specialist_graph(
        specialist="account",
        llm=worker_llm,
        tools=account_tools,
        tooling_summary=toolbox.describe_account_tooling(),
    )
    market_graph = build_specialist_graph(
        specialist="market",
        llm=worker_llm,
        tools=market_tools,
        tooling_summary=toolbox.describe_market_tooling(),
    )

    builder = StateGraph(BusinessAssistantState)
    builder.add_node("memory_recall", build_memory_recall_node(memory_store, history_window=history_window))
    builder.add_node("intent_analyst", build_intent_analyst_node(router_llm, worker_llm))
    builder.add_node("route_guard", build_route_guard_node())
    builder.add_node("mercadolibre_account", build_account_dispatch_node(account_graph))
    builder.add_node("market_intelligence", build_market_dispatch_node(market_graph))
    builder.add_node("clarification", build_clarification_node(worker_llm))
    builder.add_node("memory_writer", build_memory_writer_node(memory_store))

    builder.add_edge(START, "memory_recall")
    builder.add_edge("memory_recall", "intent_analyst")
    builder.add_edge("intent_analyst", "route_guard")
    builder.add_conditional_edges(
        "route_guard",
        _route_after_guard,
        {
            "mercadolibre_account": "mercadolibre_account",
            "market_intelligence": "market_intelligence",
            "clarification": "clarification",
        },
    )
    builder.add_edge("mercadolibre_account", "memory_writer")
    builder.add_edge("market_intelligence", "memory_writer")
    builder.add_edge("clarification", "memory_writer")
    builder.add_edge("memory_writer", END)

    return builder.compile()
