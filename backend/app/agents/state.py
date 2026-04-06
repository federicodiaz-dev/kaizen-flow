from __future__ import annotations

from typing import Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import Annotated


AssistantRoute = Literal["mercadolibre_account", "market_intelligence", "clarification"]


class BusinessAssistantState(TypedDict, total=False):
    thread_id: str
    account_key: str
    site_id: str
    user_input: str
    chat_history: str
    route: AssistantRoute
    selected_agent: str
    user_goal: str
    normalized_request: str
    intent_confidence: float
    reasoning: str
    needs_account_context: bool
    needs_market_context: bool
    required_data_points: list[str]
    clarifying_question: str
    final_response: str
    response_metadata: dict[str, Any]


class SpecializedAgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    account_key: str
    site_id: str
    user_input: str
    chat_history: str
    user_goal: str
    normalized_request: str
    required_data_points: list[str]
    final_response: str
