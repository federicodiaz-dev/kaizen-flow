from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from app.core.env_parser import parse_env_file


ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT_DIR / ".env"


def _first(values: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = values.get(key)
        if value not in (None, ""):
            return value
    return None


def _to_bool(value: Any | None, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _to_float(value: Any | None, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _to_int(value: Any | None, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _to_optional_int(value: Any | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _to_list(value: Any | None) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _to_dict(value: Any | None) -> dict[str, str]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(item) for key, item in parsed.items()}


@dataclass(frozen=True, slots=True)
class MCPConnectionSettings:
    enabled: bool
    server_name: str
    transport: Literal["http", "stdio"]
    url: str | None
    command: str | None
    args: tuple[str, ...]
    headers: dict[str, str]
    env: dict[str, str]
    cwd: str | None

    def to_connection_config(self) -> dict[str, Any] | None:
        if not self.enabled:
            return None

        if self.transport == "http":
            if not self.url:
                raise ValueError("AI_MCP_URL is required when AI_MCP_TRANSPORT is 'http'.")
            payload: dict[str, Any] = {
                "transport": "http",
                "url": self.url,
            }
            if self.headers:
                payload["headers"] = self.headers
            return payload

        if not self.command:
            raise ValueError("AI_MCP_COMMAND is required when AI_MCP_TRANSPORT is 'stdio'.")

        payload = {
            "transport": "stdio",
            "command": self.command,
        }
        if self.args:
            payload["args"] = list(self.args)
        if self.env:
            payload["env"] = self.env
        if self.cwd:
            payload["cwd"] = self.cwd
        return payload


@dataclass(frozen=True, slots=True)
class AgentSettings:
    groq_api_key: str
    groq_model: str
    groq_router_model: str
    temperature: float
    router_temperature: float
    default_site_id: str
    history_window: int
    memory_dir: Path
    token_report_enabled: bool
    token_report_dir: Path
    token_budget_tokens: int | None
    token_budget_window: Literal["daily", "monthly", "all_time"]
    mcp: MCPConnectionSettings

    def validate_runtime(self) -> None:
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY is required to use the AI assistant.")
        if len(self.default_site_id.strip()) < 3:
            raise ValueError("AI_DEFAULT_SITE_ID must be a valid Mercado Libre site id.")
        if self.history_window < 1:
            raise ValueError("AI_HISTORY_WINDOW must be greater than zero.")
        if self.mcp.enabled:
            self.mcp.to_connection_config()


@lru_cache(maxsize=1)
def get_agent_settings() -> AgentSettings:
    env_file_values, _ = parse_env_file(ENV_PATH)
    merged_values: dict[str, Any] = {**env_file_values, **os.environ}

    raw_memory_dir = str(_first(merged_values, "AI_MEMORY_DIR") or "backend/data/agents")
    memory_dir = Path(raw_memory_dir)
    if not memory_dir.is_absolute():
        memory_dir = ROOT_DIR / memory_dir

    raw_token_report_dir = str(_first(merged_values, "AI_TOKEN_REPORT_DIR") or "backend/data/ai_usage_reports")
    token_report_dir = Path(raw_token_report_dir)
    if not token_report_dir.is_absolute():
        token_report_dir = ROOT_DIR / token_report_dir

    token_budget_window = str(_first(merged_values, "AI_TOKEN_REPORT_BUDGET_WINDOW") or "monthly").strip().lower()
    if token_budget_window not in {"daily", "monthly", "all_time"}:
        token_budget_window = "monthly"

    mcp_transport = str(_first(merged_values, "AI_MCP_TRANSPORT") or "http").strip().lower()
    if mcp_transport not in {"http", "stdio"}:
        mcp_transport = "http"

    mcp_url = str(_first(merged_values, "AI_MCP_URL") or "").strip() or None
    mcp_command = str(_first(merged_values, "AI_MCP_COMMAND") or "").strip() or None
    mcp_enabled = _to_bool(
        _first(merged_values, "AI_MCP_ENABLED"),
        default=bool(mcp_url or mcp_command),
    )

    return AgentSettings(
        groq_api_key=str(_first(merged_values, "GROQ_API_KEY") or "").strip(),
        groq_model=str(
            _first(
                merged_values,
                "GROQ_MODEL",
                "AI_GROQ_MODEL",
            )
            or "llama-3.3-70b-versatile"
        ).strip(),
        groq_router_model=str(
            _first(
                merged_values,
                "GROQ_ROUTER_MODEL",
                "AI_GROQ_ROUTER_MODEL",
            )
            or "openai/gpt-oss-20b"
        ).strip(),
        temperature=_to_float(_first(merged_values, "AI_TEMPERATURE"), 0.1),
        router_temperature=_to_float(_first(merged_values, "AI_ROUTER_TEMPERATURE"), 0.0),
        default_site_id=str(_first(merged_values, "AI_DEFAULT_SITE_ID") or "MLA").strip().upper(),
        history_window=_to_int(_first(merged_values, "AI_HISTORY_WINDOW"), 8),
        memory_dir=memory_dir,
        token_report_enabled=_to_bool(_first(merged_values, "AI_TOKEN_REPORT_ENABLED"), default=True),
        token_report_dir=token_report_dir,
        token_budget_tokens=_to_optional_int(_first(merged_values, "AI_TOKEN_REPORT_BUDGET_TOKENS")),
        token_budget_window=token_budget_window,
        mcp=MCPConnectionSettings(
            enabled=mcp_enabled,
            server_name=str(_first(merged_values, "AI_MCP_SERVER_NAME") or "mercadolibre").strip(),
            transport=mcp_transport,
            url=mcp_url,
            command=mcp_command,
            args=tuple(_to_list(_first(merged_values, "AI_MCP_ARGS_JSON"))),
            headers=_to_dict(_first(merged_values, "AI_MCP_HEADERS_JSON")),
            env=_to_dict(_first(merged_values, "AI_MCP_ENV_JSON")),
            cwd=str(_first(merged_values, "AI_MCP_CWD") or "").strip() or None,
        ),
    )
