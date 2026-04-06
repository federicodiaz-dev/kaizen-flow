from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AgentRoute = Literal["mercadolibre_account", "market_intelligence", "clarification"]


class AgentIntentMetadata(BaseModel):
    route: AgentRoute = "clarification"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    user_goal: str = ""
    normalized_request: str = ""
    needs_account_context: bool = False
    needs_market_context: bool = False
    required_data_points: list[str] = Field(default_factory=list)
    clarifying_question: str | None = None
    reasoning: str = ""


class AgentChatMessage(BaseModel):
    role: str
    content: str
    created_at: str
    metadata: dict[str, Any] | None = None


class AgentThreadSummary(BaseModel):
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    last_message_preview: str


class AgentThreadDetail(AgentThreadSummary):
    messages: list[AgentChatMessage] = Field(default_factory=list)


class AgentMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=12000)
    site_id: str | None = Field(default=None, min_length=3, max_length=4)


class AgentMessageResponse(BaseModel):
    thread: AgentThreadDetail
    assistant_message: AgentChatMessage
    final_response: str
    route: AgentRoute
    intent: AgentIntentMetadata
    account_key: str
    site_id: str


class AgentsHealthResponse(BaseModel):
    status: str
    llm_provider: str
    model: str
    router_model: str
    mcp_configured: bool
    mcp_available: bool
    mcp_error: str | None = None
