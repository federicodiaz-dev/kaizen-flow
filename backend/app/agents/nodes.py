from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.core.ai_usage_reporting import llm_run_config
from app.agents.memory import JsonAgentMemoryStore
from app.agents.prompts import ACCOUNT_AGENT_PROMPT, INTENT_ANALYST_PROMPT, MARKET_AGENT_PROMPT, SMART_CLARIFICATION_PROMPT
from app.agents.state import BusinessAssistantState, SpecializedAgentState
from app.schemas.agents import AgentIntentMetadata


INTENT_CONFIDENCE_THRESHOLD = 0.40
logger = logging.getLogger("kaizen-flow.agents")




def _extract_previous_route(chat_history: str) -> str | None:
    """Extract the route from the most recent assistant message metadata in chat history."""
    # Look for route patterns in the serialized history
    lines = chat_history.strip().split("\n")
    for line in reversed(lines):
        lowered = line.lower()
        if "mercadolibre_account" in lowered:
            return "mercadolibre_account"
        if "market_intelligence" in lowered:
            return "market_intelligence"
    return None


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


def _is_tool_use_failed_error(exc: Exception) -> bool:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("code") == "tool_use_failed":
            return True
    lowered = str(exc).lower()
    return "tool_use_failed" in lowered or "failed to call a function" in lowered


def _extract_failed_generation(exc: Exception) -> str | None:
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    failed_generation = error.get("failed_generation")
    if isinstance(failed_generation, str) and failed_generation.strip():
        return failed_generation.strip()
    return None


def _append_recovery_instruction(
    messages: list[BaseMessage],
    *,
    specialist: str,
) -> list[BaseMessage]:
    if specialist == "account":
        instruction = (
            "Tool calling failed in the previous attempt. Do not call any tools now. "
            "Answer directly using only the conversation and any prior tool outputs already present. "
            "Do not invent account-specific facts, counts, statuses, policies, URLs, or claim details. "
            "If live verification is still needed, say so clearly and ask for the claim id, item id, or a retry. "
            "Avoid markdown links."
        )
    else:
        instruction = (
            "Tool calling failed in the previous attempt. Do not call any tools now. "
            "Answer directly using only the conversation and any prior tool outputs already present. "
            "Be explicit about uncertainty and avoid invented URLs or citations. "
            "Avoid markdown links."
        )
    return [*messages, SystemMessage(content=instruction)]


def _safe_reasoner_fallback_message(*, specialist: str) -> str:
    if specialist == "account":
        return (
            "## Respuesta\n"
            "Tuve un problema al consultar las herramientas en este intento, así que no pude verificar datos en vivo de la cuenta.\n\n"
            "## Evidencia Utilizada\n"
            "No hubo salida confiable de herramientas en esta ejecución.\n\n"
            "## Siguiente Paso\n"
            "Probá de nuevo o pasame el ID del reclamo, pregunta o publicación que querés revisar para acotar la consulta."
        )
    return (
        "## Recomendacion Principal\n"
        "Tuve un problema al consultar herramientas en este intento, así que no puedo sostener una recomendación fuerte con datos verificados.\n\n"
        "## Por Que Tiene Sentido\n"
        "Prefiero no inventar señales de mercado cuando la consulta no quedó validada.\n\n"
        "## Riesgos O Dudas\n"
        "La respuesta podría ser incompleta sin datos en vivo.\n\n"
        "## Siguiente Validacion\n"
        "Probá de nuevo con una consulta más puntual para que pueda verificarla mejor."
    )


def build_memory_recall_node(memory_store: JsonAgentMemoryStore, *, history_window: int):
    def memory_recall(state: BusinessAssistantState) -> dict[str, Any]:
        snapshot = memory_store.load_snapshot(state["thread_id"], limit=history_window)
        return {"chat_history": snapshot.chat_history}

    return memory_recall


def build_intent_analyst_node(router_llm, worker_llm=None):
    """Build the intent analyst using a dual-LLM strategy: primary router + worker fallback."""
    structured_llm = router_llm.with_structured_output(AgentIntentMetadata)
    fallback_structured_llm = (
        worker_llm.with_structured_output(AgentIntentMetadata) if worker_llm else None
    )

    async def _invoke_llm_routing(llm_to_use, raw_llm, messages: list) -> AgentIntentMetadata | None:
        """Attempt structured output, then raw JSON parse, return None if all fail."""
        # Attempt 1: structured output
        try:
            decision = await llm_to_use.ainvoke(
                messages,
                config=llm_run_config("agents.intent_routing.structured"),
            )
            return (
                decision
                if isinstance(decision, AgentIntentMetadata)
                else AgentIntentMetadata.model_validate(decision)
            )
        except Exception:
            pass

        # Attempt 2: raw invocation + JSON extraction
        try:
            raw_response = await raw_llm.ainvoke(
                messages,
                config=llm_run_config("agents.intent_routing.raw_fallback"),
            )
            payload = _extract_json_payload(_stringify_message_content(raw_response.content))
            if payload:
                return AgentIntentMetadata.model_validate(payload)
        except Exception:
            pass

        return None

    async def intent_analyst(state: BusinessAssistantState) -> dict[str, Any]:
        user_input = state["user_input"].strip()
        history = state.get("chat_history", "No prior conversation in this thread.")

        # Detect previous routing context for conversation continuity
        previous_route = _extract_previous_route(history)
        context_hint = ""
        if previous_route:
            context_hint = (
                f"\n\nIMPORTANT CONTEXT: The previous turn in this conversation was routed to '{previous_route}'. "
                f"If the current message is a follow-up or continuation, strongly prefer the same route."
            )

        messages = [
            SystemMessage(content=INTENT_ANALYST_PROMPT),
            HumanMessage(
                content=(
                    f"Recent conversation:\n{history}\n\n"
                    f"Latest user message:\n{user_input}\n\n"
                    f"{context_hint}\n\n"
                    "Return the routing decision."
                )
            ),
        ]

        # ── Primary LLM (router model) ──
        parsed = await _invoke_llm_routing(structured_llm, router_llm, messages)

        # ── Fallback LLM (worker model, typically more capable) ──
        if parsed is None and fallback_structured_llm is not None:
            parsed = await _invoke_llm_routing(fallback_structured_llm, worker_llm, messages)

        # ── If both LLMs fail entirely, use clarification with a friendly message ──
        if parsed is None:
            return {
                "route": "clarification",
                "user_goal": "",
                "normalized_request": user_input,
                "intent_confidence": 0.5,
                "reasoning": "Both primary and fallback LLMs failed to produce a routing decision.",
                "needs_account_context": False,
                "needs_market_context": False,
                "required_data_points": [],
                "clarifying_question": (
                    "Disculpá, tuve un problema procesando tu mensaje. "
                    "¿Podrías reformularlo? Puedo ayudarte con tu cuenta de Mercado Libre o análisis de mercado."
                ),
            }

        # Apply conversation continuity boost
        route = parsed.route
        confidence = parsed.confidence

        if previous_route and route == previous_route and confidence < 0.85:
            confidence = max(confidence, 0.85)

        # If low confidence but previous route exists, inherit it
        if confidence < INTENT_CONFIDENCE_THRESHOLD and previous_route:
            route = previous_route
            confidence = 0.70

        return {
            "route": route,
            "user_goal": parsed.user_goal,
            "normalized_request": parsed.normalized_request or user_input,
            "intent_confidence": confidence,
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
            }

        selected_agent = (
            "mercadolibre_account_agent"
            if route == "mercadolibre_account"
            else "market_intelligence_agent"
        )
        return {"selected_agent": selected_agent}

    return route_guard


def build_clarification_node(clarification_llm=None):
    async def clarification(state: BusinessAssistantState) -> dict[str, Any]:
        # If there's already a clarifying question from the router, use it
        existing = (state.get("clarifying_question") or "").strip()
        if existing and state.get("final_response"):
            return {}

        if existing:
            return {"final_response": existing}

        # Use LLM to generate intelligent clarification
        if clarification_llm is not None:
            try:
                user_input = state.get("user_input", "").strip()
                history = state.get("chat_history", "No prior conversation.")

                messages = [
                    SystemMessage(content=SMART_CLARIFICATION_PROMPT),
                    HumanMessage(
                        content=(
                            f"Chat history:\n{history}\n\n"
                            f"User's latest message:\n{user_input}\n\n"
                            "Generate a friendly, contextual clarification."
                        )
                    ),
                ]
                response = await clarification_llm.ainvoke(
                    messages,
                    config=llm_run_config("agents.clarification"),
                )
                text = _stringify_message_content(response.content).strip()
                if text:
                    return {"final_response": text}
            except Exception:
                pass

        # Fallback: at least be friendly
        return {
            "final_response": (
                "¡Hola! No estuve seguro de interpretar tu mensaje. "
                "¿Querés que revise algo de tu cuenta de Mercado Libre "
                "(publicaciones, reclamos, preguntas) o preferís analizar el mercado?"
            ),
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


def build_tool_reasoner_node(bound_model, llm, *, specialist: str):
    async def tool_reasoner(state: SpecializedAgentState) -> dict[str, Any]:
        messages = state.get("messages", [])
        try:
            response = await bound_model.ainvoke(
                messages,
                config=llm_run_config(f"agents.{specialist}.tool_reasoner"),
            )
            return {"messages": [response]}
        except Exception as exc:
            if not _is_tool_use_failed_error(exc):
                raise

            failed_generation = _extract_failed_generation(exc)
            if failed_generation:
                logger.warning(
                    "Groq tool calling failed for %s specialist. Failed generation: %s",
                    specialist,
                    failed_generation,
                )
            else:
                logger.warning(
                    "Groq tool calling failed for %s specialist.",
                    specialist,
                    exc_info=True,
                )

            recovery_messages = _append_recovery_instruction(messages, specialist=specialist)
            try:
                recovery_response = await llm.ainvoke(
                    recovery_messages,
                    config=llm_run_config(f"agents.{specialist}.tool_reasoner_recovery"),
                )
                return {"messages": [recovery_response]}
            except Exception:
                logger.warning(
                    "Direct-answer fallback also failed for %s specialist.",
                    specialist,
                    exc_info=True,
                )
                return {"messages": [AIMessage(content=_safe_reasoner_fallback_message(specialist=specialist))]}

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
