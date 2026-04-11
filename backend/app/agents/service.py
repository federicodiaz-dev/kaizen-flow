from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.agents.config import AgentSettings, get_agent_settings
from app.agents.memory import JsonAgentMemoryStore, fallback_thread_title
from app.core.account_store import AccountStore
from app.core.exceptions import BadRequestError, ConfigurationError
from app.core.settings import Settings
from app.schemas.agents import AgentIntentMetadata


class BusinessAssistantService:
    def __init__(
        self,
        *,
        settings: Settings,
        account_store: AccountStore,
        http_client: httpx.AsyncClient,
        agent_settings: AgentSettings | None = None,
    ) -> None:
        self._settings = settings
        self._account_store = account_store
        self._http_client = http_client
        self._agent_settings = agent_settings or get_agent_settings()
        self.memory_store = JsonAgentMemoryStore(self._agent_settings.memory_dir)
        self.toolbox = None
        self._graph = None
        self._ready_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self.toolbox is not None:
            await self.toolbox.aclose()

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "llm_provider": "google_ai_studio",
            "model": self._agent_settings.google_model,
            "router_model": self._agent_settings.google_router_model,
            "mcp_configured": self._agent_settings.mcp.enabled,
            "mcp_available": bool(self.toolbox and self.toolbox.mcp_available),
            "mcp_error": self.toolbox.mcp_error if self.toolbox is not None else None,
        }

    def list_threads(self) -> list[dict[str, Any]]:
        return [record.to_summary_dict() for record in self.memory_store.list_threads()]

    def create_thread(self) -> dict[str, Any]:
        return self.memory_store.create_thread().to_dict()

    def get_thread(self, thread_id: str) -> dict[str, Any]:
        return self.memory_store.ensure_thread(thread_id).to_dict()

    async def send_message(
        self,
        *,
        thread_id: str,
        user_input: str,
        account_key: str,
        site_id: str | None = None,
    ) -> dict[str, Any]:
        clean_input = user_input.strip()
        if not clean_input:
            raise BadRequestError("Message content cannot be empty.")

        await self._ensure_ready()

        active_site_id = (site_id or self._agent_settings.default_site_id).strip().upper()
        thread = self.memory_store.ensure_thread(thread_id)
        had_user_messages = any(message.role == "user" for message in thread.messages)

        if self.toolbox is None:
            raise ConfigurationError("The AI assistant is not initialized.")

        with self.toolbox.bind_runtime_context(account_key=account_key, site_id=active_site_id):
            result = await self._graph.ainvoke(
                {
                    "thread_id": thread_id,
                    "account_key": account_key,
                    "site_id": active_site_id,
                    "user_input": clean_input,
                }
            )

        if not had_user_messages:
            self.memory_store.set_title(
                thread_id,
                fallback_thread_title(result.get("normalized_request", clean_input)),
            )

        updated_thread = self.memory_store.get_thread(thread_id)
        assistant_message = (
            updated_thread.messages[-1].to_dict()
            if updated_thread.messages
            else {"role": "assistant", "content": result.get("final_response", ""), "created_at": ""}
        )

        intent = AgentIntentMetadata(
            route=result.get("route", "clarification"),
            confidence=float(result.get("intent_confidence") or 0.0),
            user_goal=result.get("user_goal", ""),
            normalized_request=result.get("normalized_request", clean_input),
            needs_account_context=bool(result.get("needs_account_context") or False),
            needs_market_context=bool(result.get("needs_market_context") or False),
            required_data_points=list(result.get("required_data_points") or []),
            clarifying_question=result.get("clarifying_question"),
            reasoning=result.get("reasoning", ""),
        )

        return {
            "thread": updated_thread.to_dict(),
            "assistant_message": assistant_message,
            "final_response": result.get("final_response", ""),
            "route": result.get("route", "clarification"),
            "intent": intent.model_dump(mode="json"),
            "account_key": account_key,
            "site_id": active_site_id,
        }

    async def _ensure_ready(self) -> None:
        if self._graph is not None:
            return

        async with self._ready_lock:
            if self._graph is not None:
                return

            try:
                from app.agents.llm import build_chat_models
                from app.agents.toolbox import AgentToolbox
                from app.agents.workflow import build_business_assistant_graph
            except ImportError as exc:  # pragma: no cover
                raise ConfigurationError(
                    "AI dependencies are not installed. Reinstall backend requirements before using the assistant.",
                    details={"missing_dependency": str(exc)},
                ) from exc

            try:
                self.toolbox = AgentToolbox(
                    agent_settings=self._agent_settings,
                    core_settings=self._settings,
                    account_store=self._account_store,
                    http_client=self._http_client,
                )
                router_llm, worker_llm = build_chat_models(self._agent_settings)
                self._graph = await build_business_assistant_graph(
                    router_llm=router_llm,
                    worker_llm=worker_llm,
                    memory_store=self.memory_store,
                    toolbox=self.toolbox,
                    history_window=self._agent_settings.history_window,
                )
            except ValueError as exc:
                raise ConfigurationError(str(exc)) from exc
            except Exception as exc:
                raise ConfigurationError(
                    "Could not initialize the AI assistant.",
                    details={"error": str(exc)},
                ) from exc
