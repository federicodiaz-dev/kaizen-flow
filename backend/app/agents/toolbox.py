from __future__ import annotations

import asyncio
import logging
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from statistics import fmean, median
from typing import Any

import httpx
from langchain_core.tools import BaseTool, tool

from app.adapters.claims import ClaimsAdapter
from app.adapters.items import ItemsAdapter
from app.adapters.questions import QuestionsAdapter
from app.agents.config import AgentSettings
from app.clients.mercadolibre import MercadoLibreClient
from app.core.account_store import AccountStore
from app.core.exceptions import AppError
from app.core.settings import Settings
from app.schemas.accounts import AccountsResponse
from app.services.accounts import AccountsService
from app.services.claims import ClaimsService
from app.services.items import ItemsService
from app.services.questions import QuestionsService


logger = logging.getLogger("kaizen-flow.agents")

READ_ONLY_MUTATION_HINTS = {
    "answer",
    "create",
    "delete",
    "edit",
    "patch",
    "post",
    "reply",
    "send",
    "update",
    "write",
}


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    account_key: str
    site_id: str


class AgentToolbox:
    def __init__(
        self,
        *,
        agent_settings: AgentSettings,
        core_settings: Settings,
        account_store: AccountStore,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._agent_settings = agent_settings
        self._runtime_context: ContextVar[RuntimeContext | None] = ContextVar(
            "kaizen_flow_agent_runtime_context",
            default=None,
        )
        self._ml_client = MercadoLibreClient(
            http_client=http_client,
            settings=core_settings,
            account_store=account_store,
        )
        self._account_store = account_store
        self._accounts_service = AccountsService(account_store=account_store)
        self._items_service = ItemsService(
            account_store=account_store,
            client=self._ml_client,
            items_adapter=ItemsAdapter(self._ml_client),
        )
        self._questions_service = QuestionsService(
            account_store=account_store,
            client=self._ml_client,
            questions_adapter=QuestionsAdapter(self._ml_client),
            items_adapter=ItemsAdapter(self._ml_client),
        )
        self._claims_service = ClaimsService(
            account_store=account_store,
            client=self._ml_client,
            claims_adapter=ClaimsAdapter(self._ml_client),
        )

        self._local_account_tools = self._build_local_account_tools()
        self._local_market_tools = self._build_local_market_tools()
        self._mcp_client: Any | None = None
        self._mcp_tools: list[BaseTool] | None = None
        self._mcp_error: str | None = None
        self._mcp_lock = asyncio.Lock()

    @property
    def mcp_configured(self) -> bool:
        return self._agent_settings.mcp.enabled

    @property
    def mcp_available(self) -> bool:
        return bool(self._mcp_tools)

    @property
    def mcp_error(self) -> str | None:
        return self._mcp_error

    @contextmanager
    def bind_runtime_context(self, *, account_key: str, site_id: str):
        token = self._runtime_context.set(RuntimeContext(account_key=account_key, site_id=site_id))
        try:
            yield
        finally:
            self._runtime_context.reset(token)

    async def aclose(self) -> None:
        if self._mcp_client is None:
            return
        close = getattr(self._mcp_client, "close", None)
        if close is None:
            return
        try:
            result = close()
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # pragma: no cover
            logger.warning("Could not close MCP client cleanly.", exc_info=True)

    async def get_account_tools(self) -> list[BaseTool]:
        return [*(await self._load_mcp_tools()), *self._local_account_tools]

    async def get_market_tools(self) -> list[BaseTool]:
        return [*(await self._load_mcp_tools()), *self._local_market_tools]

    def describe_account_tooling(self) -> str:
        parts: list[str] = []
        if self._mcp_tools:
            sample = ", ".join(tool.name for tool in self._mcp_tools[:10])
            parts.append(f"Read-only MCP tools available: {sample}.")
        elif self._agent_settings.mcp.enabled:
            parts.append(f"MCP configured but unavailable: {self._mcp_error or 'tool loading failed'}.")
        else:
            parts.append("No MCP server is configured in this environment.")
        parts.append(
            "Local compatibility tools available: "
            + ", ".join(tool.name for tool in self._local_account_tools)
            + "."
        )
        return " ".join(parts)

    def describe_market_tooling(self) -> str:
        parts: list[str] = []
        if self._mcp_tools:
            sample = ", ".join(tool.name for tool in self._mcp_tools[:10])
            parts.append(f"Read-only MCP tools available: {sample}.")
        elif self._agent_settings.mcp.enabled:
            parts.append(f"MCP configured but unavailable: {self._mcp_error or 'tool loading failed'}.")
        else:
            parts.append("No MCP server is configured in this environment.")
        parts.append(
            "Local market tools available: "
            + ", ".join(tool.name for tool in self._local_market_tools)
            + "."
        )
        return " ".join(parts)

    async def _load_mcp_tools(self) -> list[BaseTool]:
        if self._mcp_tools is not None:
            return self._mcp_tools

        if not self._agent_settings.mcp.enabled:
            self._mcp_tools = []
            return self._mcp_tools

        async with self._mcp_lock:
            if self._mcp_tools is not None:
                return self._mcp_tools

            try:
                from langchain_mcp_adapters.client import MultiServerMCPClient
            except ImportError as exc:  # pragma: no cover
                self._mcp_error = "langchain-mcp-adapters is not installed."
                raise RuntimeError(self._mcp_error) from exc

            try:
                connection = self._agent_settings.mcp.to_connection_config()
                if connection is None:
                    self._mcp_tools = []
                    return self._mcp_tools

                self._mcp_client = MultiServerMCPClient(
                    {self._agent_settings.mcp.server_name: connection},
                    tool_name_prefix=True,
                )
                loaded_tools = await self._mcp_client.get_tools()
                self._mcp_tools = [tool for tool in loaded_tools if self._is_safe_read_only_tool(tool)]
                return self._mcp_tools
            except Exception as exc:  # pragma: no cover
                self._mcp_error = str(exc)
                logger.warning("Could not load Mercado Libre MCP tools.", exc_info=True)
                self._mcp_tools = []
                return self._mcp_tools

    @staticmethod
    def _is_safe_read_only_tool(tool_obj: BaseTool) -> bool:
        descriptor = f"{tool_obj.name} {getattr(tool_obj, 'description', '')}".lower()
        return not any(keyword in descriptor for keyword in READ_ONLY_MUTATION_HINTS)

    def _current_runtime(self) -> RuntimeContext:
        runtime = self._runtime_context.get()
        if runtime is None:
            raise RuntimeError("Agent runtime context is not bound to the current request.")
        return runtime

    @staticmethod
    def _app_error_payload(exc: AppError) -> dict[str, Any]:
        return {
            "ok": False,
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
        }

    @staticmethod
    def _unexpected_error_payload(exc: Exception) -> dict[str, Any]:
        return {
            "ok": False,
            "error": "tool_error",
            "message": str(exc),
        }

    async def _account_summary_payload(self, account_key: str) -> dict[str, Any]:
        account = self._account_store.get_account(account_key)
        me = await self._ml_client.get_me(account_key)
        available_accounts: AccountsResponse = self._accounts_service.list_accounts()
        return {
            "ok": True,
            "current_account": {
                "key": account.key,
                "label": account.label,
                "user_id": account.user_id,
                "scope": account.scope,
            },
            "user": {
                "id": me.get("id"),
                "nickname": me.get("nickname"),
                "registration_date": me.get("registration_date"),
                "country_id": me.get("country_id"),
                "site_id": me.get("site_id"),
                "points": me.get("points"),
                "seller_reputation": me.get("seller_reputation"),
                "status": me.get("status"),
                "permalink": me.get("permalink"),
            },
            "configured_accounts": [item.model_dump(mode="json") for item in available_accounts.items],
        }

    async def _items_overview_payload(
        self,
        account_key: str,
        *,
        status: str | None,
        limit: int,
    ) -> dict[str, Any]:
        response = await self._items_service.list_items(account_key, limit=min(limit, 50), offset=0, status=status)
        return {
            "ok": True,
            "status_filter": status,
            "total_items": response.total,
            "sample_items": [item.model_dump(mode="json") for item in response.items[: min(limit, 15)]],
        }

    async def _questions_overview_payload(
        self,
        account_key: str,
        *,
        limit: int,
        unanswered_only: bool,
    ) -> dict[str, Any]:
        response = await self._questions_service.list_questions(account_key, limit=min(limit, 50), offset=0)
        items = response.items
        if unanswered_only:
            items = [item for item in items if not item.has_answer]
        return {
            "ok": True,
            "total_from_api": response.total,
            "unanswered_only": unanswered_only,
            "visible_count": len(items),
            "sample_questions": [item.model_dump(mode="json") for item in items[: min(limit, 15)]],
        }

    async def _claims_overview_payload(
        self,
        account_key: str,
        *,
        limit: int,
        status: str | None,
        stage: str | None,
    ) -> dict[str, Any]:
        response = await self._claims_service.list_claims(
            account_key,
            limit=min(limit, 50),
            offset=0,
            stage=stage,
            status=status,
        )
        open_claims = [item for item in response.items if str(item.status or "").lower() != "closed"]
        return {
            "ok": True,
            "status_filter": status,
            "stage_filter": stage,
            "total_from_api": response.total,
            "open_claims_in_page": len(open_claims),
            "sample_claims": [item.model_dump(mode="json") for item in response.items[: min(limit, 12)]],
        }

    async def _business_overview_payload(self, account_key: str) -> dict[str, Any]:
        account, active_items, unanswered_questions, claims = await asyncio.gather(
            self._account_summary_payload(account_key),
            self._items_overview_payload(account_key, status="active", limit=20),
            self._questions_overview_payload(account_key, limit=20, unanswered_only=True),
            self._claims_overview_payload(account_key, limit=20, status=None, stage=None),
        )
        return {
            "ok": True,
            "account": account,
            "active_items": active_items,
            "pending_questions": unanswered_questions,
            "claims": claims,
        }

    async def _market_category_payload(self, query: str) -> dict[str, Any]:
        runtime = self._current_runtime()
        data = await self._ml_client.request(
            runtime.account_key,
            "GET",
            "/marketplace/domain_discovery/search",
            params={"q": query},
        )
        suggestions = data if isinstance(data, list) else []
        return {
            "ok": True,
            "query": query,
            "site_id": runtime.site_id,
            "suggestions": suggestions[:8],
        }

    async def _market_trends_payload(self, *, category_id: str | None, limit: int) -> dict[str, Any]:
        runtime = self._current_runtime()
        path = f"/trends/{runtime.site_id}"
        if category_id:
            path = f"{path}/{category_id}"
        data = await self._ml_client.request(runtime.account_key, "GET", path)
        raw_items = data if isinstance(data, list) else []
        items = []
        for entry in raw_items[:limit]:
            if not isinstance(entry, dict):
                continue
            items.append(
                {
                    "keyword": entry.get("keyword") or entry.get("query") or entry.get("name"),
                    "url": entry.get("url"),
                }
            )
        return {
            "ok": True,
            "site_id": runtime.site_id,
            "category_id": category_id,
            "trends": items,
        }

    async def _market_search_payload(
        self,
        *,
        query: str,
        category_id: str | None,
        limit: int,
    ) -> dict[str, Any]:
        runtime = self._current_runtime()
        params: dict[str, Any] = {
            "q": query,
            "limit": min(limit, 20),
        }
        if category_id:
            params["category"] = category_id

        data = await self._ml_client.request(
            runtime.account_key,
            "GET",
            f"/sites/{runtime.site_id}/search",
            params=params,
        )
        results = data.get("results") if isinstance(data, dict) and isinstance(data.get("results"), list) else []
        prices = [float(item["price"]) for item in results if isinstance(item, dict) and item.get("price") is not None]
        sold_quantities = [
            int(item["sold_quantity"])
            for item in results
            if isinstance(item, dict) and item.get("sold_quantity") is not None
        ]
        listing_types = Counter(
            str(item.get("listing_type_id") or "unknown")
            for item in results
            if isinstance(item, dict)
        )
        free_shipping_count = sum(
            1
            for item in results
            if isinstance(item, dict) and isinstance(item.get("shipping"), dict) and item["shipping"].get("free_shipping")
        )

        price_stats: dict[str, float] = {}
        if prices:
            price_stats = {
                "min": round(min(prices), 2),
                "max": round(max(prices), 2),
                "avg": round(fmean(prices), 2),
                "median": round(float(median(prices)), 2),
            }

        return {
            "ok": True,
            "query": query,
            "site_id": runtime.site_id,
            "category_id": category_id,
            "total_results": data.get("paging", {}).get("total") if isinstance(data, dict) else None,
            "price_stats": price_stats,
            "avg_sold_quantity": round(fmean(sold_quantities), 2) if sold_quantities else None,
            "free_shipping_share_in_sample": round(free_shipping_count / len(results), 3) if results else None,
            "listing_type_mix": dict(listing_types),
            "sample_results": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "price": item.get("price"),
                    "currency_id": item.get("currency_id"),
                    "condition": item.get("condition"),
                    "sold_quantity": item.get("sold_quantity"),
                    "listing_type_id": item.get("listing_type_id"),
                    "permalink": item.get("permalink"),
                    "free_shipping": item.get("shipping", {}).get("free_shipping") if isinstance(item.get("shipping"), dict) else None,
                }
                for item in results[: min(limit, 12)]
                if isinstance(item, dict)
            ],
        }

    async def _catalog_fit_payload(self, *, limit: int) -> dict[str, Any]:
        runtime = self._current_runtime()
        items = await self._items_service.list_items(runtime.account_key, limit=min(limit, 10), offset=0, status="active")
        detail_tasks = [self._items_service.get_item(runtime.account_key, item.id) for item in items.items[:10]]
        details = await asyncio.gather(*detail_tasks, return_exceptions=True)

        category_counter: Counter[str] = Counter()
        samples: list[dict[str, Any]] = []
        for detail in details:
            if isinstance(detail, Exception):
                continue
            category_counter[str(detail.category_id or "unknown")] += 1
            samples.append(
                {
                    "id": detail.id,
                    "title": detail.title,
                    "category_id": detail.category_id,
                    "price": detail.price,
                    "status": detail.status,
                }
            )

        return {
            "ok": True,
            "active_catalog_total": items.total,
            "top_categories_in_sample": category_counter.most_common(8),
            "sample_items": samples[:10],
        }

    def _build_local_account_tools(self) -> list[BaseTool]:
        @tool("local_account_summary")
        async def local_account_summary() -> dict[str, Any]:
            """Get a compact snapshot of the authenticated Mercado Libre account."""
            runtime = self._current_runtime()
            try:
                return await self._account_summary_payload(runtime.account_key)
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        @tool("local_business_overview")
        async def local_business_overview() -> dict[str, Any]:
            """Get a business overview combining account, active items, pending questions, and claims."""
            runtime = self._current_runtime()
            try:
                return await self._business_overview_payload(runtime.account_key)
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        @tool("local_items_overview")
        async def local_items_overview(status: str | None = None, limit: int = 20) -> dict[str, Any]:
            """List a sampled overview of the seller publications for the active account."""
            runtime = self._current_runtime()
            try:
                return await self._items_overview_payload(runtime.account_key, status=status, limit=limit)
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        @tool("local_item_detail")
        async def local_item_detail(item_id: str) -> dict[str, Any]:
            """Get the detailed data of one Mercado Libre publication by item id."""
            runtime = self._current_runtime()
            try:
                detail = await self._items_service.get_item(runtime.account_key, item_id)
                return {"ok": True, "item": detail.model_dump(mode="json")}
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        @tool("local_questions_overview")
        async def local_questions_overview(limit: int = 20, unanswered_only: bool = True) -> dict[str, Any]:
            """List a sampled overview of account questions, optionally focusing on unanswered ones."""
            runtime = self._current_runtime()
            try:
                return await self._questions_overview_payload(
                    runtime.account_key,
                    limit=limit,
                    unanswered_only=unanswered_only,
                )
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        @tool("local_question_detail")
        async def local_question_detail(question_id: int) -> dict[str, Any]:
            """Get the detailed data of a single Mercado Libre question by id."""
            runtime = self._current_runtime()
            try:
                detail = await self._questions_service.get_question(runtime.account_key, question_id)
                return {"ok": True, "question": detail.model_dump(mode="json")}
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        @tool("local_claims_overview")
        async def local_claims_overview(
            limit: int = 20,
            status: str | None = None,
            stage: str | None = None,
        ) -> dict[str, Any]:
            """List a sampled overview of claims for the active account."""
            runtime = self._current_runtime()
            try:
                return await self._claims_overview_payload(
                    runtime.account_key,
                    limit=limit,
                    status=status,
                    stage=stage,
                )
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        @tool("local_claim_detail")
        async def local_claim_detail(claim_id: int) -> dict[str, Any]:
            """Get the detailed data of a single Mercado Libre claim by id."""
            runtime = self._current_runtime()
            try:
                detail = await self._claims_service.get_claim(runtime.account_key, claim_id)
                return {"ok": True, "claim": detail.model_dump(mode="json")}
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        return [
            local_account_summary,
            local_business_overview,
            local_items_overview,
            local_item_detail,
            local_questions_overview,
            local_question_detail,
            local_claims_overview,
            local_claim_detail,
        ]

    def _build_local_market_tools(self) -> list[BaseTool]:
        @tool("local_market_category_discovery")
        async def local_market_category_discovery(query: str) -> dict[str, Any]:
            """Infer likely Mercado Libre categories and domains for a product idea."""
            try:
                return await self._market_category_payload(query)
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        @tool("local_market_trends")
        async def local_market_trends(category_id: str | None = None, limit: int = 10) -> dict[str, Any]:
            """Get a sampled trends snapshot for the current Mercado Libre site or category."""
            try:
                return await self._market_trends_payload(category_id=category_id, limit=min(limit, 20))
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        @tool("local_market_search_snapshot")
        async def local_market_search_snapshot(
            query: str,
            category_id: str | None = None,
            limit: int = 12,
        ) -> dict[str, Any]:
            """Inspect a sampled Mercado Libre search result set for competition, prices, and demand signals."""
            try:
                return await self._market_search_payload(
                    query=query,
                    category_id=category_id,
                    limit=min(limit, 20),
                )
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        @tool("local_catalog_fit_snapshot")
        async def local_catalog_fit_snapshot(limit: int = 10) -> dict[str, Any]:
            """Inspect the seller's active catalog sample to understand current categories and product mix."""
            try:
                return await self._catalog_fit_payload(limit=min(limit, 10))
            except AppError as exc:
                return self._app_error_payload(exc)
            except Exception as exc:  # pragma: no cover
                return self._unexpected_error_payload(exc)

        return [
            local_market_category_discovery,
            local_market_trends,
            local_market_search_snapshot,
            local_catalog_fit_snapshot,
        ]
