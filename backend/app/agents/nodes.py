from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.agents.memory import JsonAgentMemoryStore
from app.agents.prompts import ACCOUNT_AGENT_PROMPT, INTENT_ANALYST_PROMPT, MARKET_AGENT_PROMPT
from app.agents.state import BusinessAssistantState, SpecializedAgentState
from app.schemas.agents import AgentIntentMetadata


INTENT_CONFIDENCE_THRESHOLD = 0.65


def _stringify_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


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


def _last_ai_message_text(messages: list[BaseMessage] | None) -> str:
    for message in reversed(messages or []):
        if isinstance(message, AIMessage):
            return _stringify_message_content(message.content).strip()
    return ""


def build_memory_recall_node(memory_store: JsonAgentMemoryStore, *, history_window: int):
    def memory_recall(state: BusinessAssistantState) -> dict[str, Any]:
        snapshot = memory_store.load_snapshot(state["thread_id"], limit=history_window)
        return {"chat_history": snapshot.chat_history}

    return memory_recall


def build_intent_analyst_node(router_llm):
    structured_llm = router_llm.with_structured_output(AgentIntentMetadata)

    async def intent_analyst(state: BusinessAssistantState) -> dict[str, Any]:
        user_input = state["user_input"].strip()
        history = state.get("chat_history", "No prior conversation in this thread.")

        messages = [
            SystemMessage(content=INTENT_ANALYST_PROMPT),
            HumanMessage(
                content=(
                    f"Recent conversation:\n{history}\n\n"
                    f"Latest user message:\n{user_input}\n\n"
                    "Return the routing decision."
                )
            ),
        ]

        try:
            decision = await structured_llm.ainvoke(messages)
            parsed = decision if isinstance(decision, AgentIntentMetadata) else AgentIntentMetadata.model_validate(decision)
        except Exception:
            raw_response = await router_llm.ainvoke(messages)
            payload = _extract_json_payload(_stringify_message_content(raw_response.content))
            parsed = AgentIntentMetadata.model_validate(payload or {})

        return {
            "route": parsed.route,
            "user_goal": parsed.user_goal,
            "normalized_request": parsed.normalized_request or user_input,
            "intent_confidence": parsed.confidence,
            "reasoning": parsed.reasoning,
            "needs_account_context": parsed.needs_account_context,
            "needs_market_context": parsed.needs_market_context,
            "required_data_points": parsed.required_data_points,
            "clarifying_question": parsed.clarifying_question,
        }

    return intent_analyst


def build_route_guard_node():
    def route_guard(state: BusinessAssistantState) -> dict[str, Any]:
        route = state.get("route", "clarification")
        confidence = float(state.get("intent_confidence") or 0.0)
        clarification = (state.get("clarifying_question") or "").strip()

        if route == "clarification" or confidence < INTENT_CONFIDENCE_THRESHOLD:
            return {
                "route": "clarification",
                "selected_agent": "clarification",
                "final_response": clarification
                or "Necesito una precision corta para ayudarte bien: queres revisar tu cuenta actual de Mercado Libre o queres analizar mercado/productos?",
            }

        selected_agent = (
            "mercadolibre_account_agent"
            if route == "mercadolibre_account"
            else "market_intelligence_agent"
        )
        return {"selected_agent": selected_agent}

    return route_guard


def build_clarification_node():
    def clarification(state: BusinessAssistantState) -> dict[str, Any]:
        if state.get("final_response"):
            return {}
        return {
            "final_response": "Necesito una aclaracion mas puntual para poder ayudarte sin asumir mal tu objetivo.",
        }

    return clarification


def build_prepare_specialist_context_node(*, specialist: str, tooling_summary: str):
    system_prompt = ACCOUNT_AGENT_PROMPT if specialist == "account" else MARKET_AGENT_PROMPT

    def prepare_context(state: SpecializedAgentState) -> dict[str, Any]:
        required_data_points = state.get("required_data_points") or []
        material = (
            f"Recent conversation:\n{state.get('chat_history', 'No prior conversation in this thread.')}\n\n"
            f"Active account key:\n{state.get('account_key', 'unknown')}\n\n"
            f"Mercado Libre site:\n{state.get('site_id', 'unknown')}\n\n"
            f"Normalized request:\n{state.get('normalized_request', state.get('user_input', ''))}\n\n"
            f"Detected user goal:\n{state.get('user_goal', '')}\n\n"
            f"Required data points:\n{json.dumps(required_data_points, ensure_ascii=False)}\n\n"
            f"Tooling status:\n{tooling_summary}\n\n"
            f"Latest user message:\n{state.get('user_input', '')}"
        )
        return {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=material),
            ]
        }

    return prepare_context


def build_tool_reasoner_node(bound_model):
    async def tool_reasoner(state: SpecializedAgentState) -> dict[str, Any]:
        response = await bound_model.ainvoke(state.get("messages", []))
        return {"messages": [response]}

    return tool_reasoner


def specialist_tools_route(state: SpecializedAgentState) -> str:
    messages = state.get("messages") or []
    if not messages:
        return "finalize"
    last_message = messages[-1]
    tool_calls = getattr(last_message, "tool_calls", None) or []
    return "tools" if tool_calls else "finalize"


def build_finalize_specialist_node():
    def finalize(state: SpecializedAgentState) -> dict[str, Any]:
        return {"final_response": _last_ai_message_text(state.get("messages"))}

    return finalize


def build_account_dispatch_node(account_graph):
    async def dispatch_account(state: BusinessAssistantState) -> dict[str, Any]:
        result = await account_graph.ainvoke(
            {
                "messages": [],
                "account_key": state["account_key"],
                "site_id": state["site_id"],
                "user_input": state["user_input"],
                "chat_history": state.get("chat_history", ""),
                "user_goal": state.get("user_goal", ""),
                "normalized_request": state.get("normalized_request", state["user_input"]),
                "required_data_points": state.get("required_data_points", []),
            }
        )
        return {"final_response": result.get("final_response", "")}

    return dispatch_account


def build_market_dispatch_node(market_graph):
    async def dispatch_market(state: BusinessAssistantState) -> dict[str, Any]:
        result = await market_graph.ainvoke(
            {
                "messages": [],
                "account_key": state["account_key"],
                "site_id": state["site_id"],
                "user_input": state["user_input"],
                "chat_history": state.get("chat_history", ""),
                "user_goal": state.get("user_goal", ""),
                "normalized_request": state.get("normalized_request", state["user_input"]),
                "required_data_points": state.get("required_data_points", []),
            }
        )
        return {"final_response": result.get("final_response", "")}

    return dispatch_market


def build_memory_writer_node(memory_store: JsonAgentMemoryStore):
    def memory_writer(state: BusinessAssistantState) -> dict[str, Any]:
        assistant_metadata = {
            "route": state.get("route"),
            "selected_agent": state.get("selected_agent"),
            "intent_confidence": state.get("intent_confidence"),
            "normalized_request": state.get("normalized_request"),
            "user_goal": state.get("user_goal"),
            "account_key": state.get("account_key"),
            "site_id": state.get("site_id"),
        }
        user_metadata = {
            "account_key": state.get("account_key"),
            "site_id": state.get("site_id"),
        }
        memory_store.append_turn(
            state["thread_id"],
            state["user_input"],
            state.get("final_response", ""),
            user_metadata=user_metadata,
            assistant_metadata=assistant_metadata,
        )
        return {}

    return memory_writer
