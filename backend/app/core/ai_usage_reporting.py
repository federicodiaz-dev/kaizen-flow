from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from app.agents.config import AgentSettings


_REPORT_LOCK = threading.Lock()
_PREVIEW_LIMIT = 480


def llm_run_config(
    operation: str,
    *,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"ai_operation": operation}
    for key, value in (extra_metadata or {}).items():
        if value not in (None, ""):
            metadata[str(key)] = value
    return {"metadata": metadata}


def create_chat_model(
    settings: AgentSettings,
    *,
    model: str,
    temperature: float,
    feature: str,
    max_retries: int = 2,
):
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing AI dependencies. Install the updated backend requirements to enable the assistant.",
        ) from exc

    callbacks = None
    if settings.token_report_enabled:
        callbacks = [
            TokenUsageCallbackHandler(
                report_dir=settings.token_report_dir,
                feature=feature,
                budget_tokens=settings.token_budget_tokens,
                budget_window=settings.token_budget_window,
            )
        ]

    return ChatGoogleGenerativeAI(
        google_api_key=settings.google_api_key,
        model=model,
        temperature=temperature,
        max_retries=max_retries,
        callbacks=callbacks,
        metadata={"ai_feature": feature},
        tags=["kaizen-flow-ai", _tagify(feature)],
    )


class TokenUsageCallbackHandler(BaseCallbackHandler):
    def __init__(
        self,
        *,
        report_dir: Path,
        feature: str,
        budget_tokens: int | None,
        budget_window: str,
    ) -> None:
        self._report_dir = Path(report_dir)
        self._feature = str(feature or "unknown")
        self._budget_tokens = budget_tokens if budget_tokens and budget_tokens > 0 else None
        self._budget_window = budget_window if budget_window in {"daily", "monthly", "all_time"} else "monthly"
        self._contexts: dict[str, dict[str, Any]] = {}
        self._contexts_lock = threading.Lock()

    async def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        prompt_preview = _messages_preview(messages)
        self._store_context(
            run_id=run_id,
            serialized=serialized,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
            prompt_preview=prompt_preview,
        )

    async def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        prompt_preview = _truncate(_collapse_whitespace("\n\n".join(prompts)))
        self._store_context(
            run_id=run_id,
            serialized=serialized,
            parent_run_id=parent_run_id,
            tags=tags,
            metadata=metadata,
            prompt_preview=prompt_preview,
        )

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        context = self._pop_context(run_id)
        summary = _extract_response_summary(response)
        timestamp = _now_iso()
        entry = {
            "timestamp": timestamp,
            "status": "ok",
            "feature": _value_or_default(context.get("feature"), self._feature),
            "operation": _value_or_default(context.get("operation"), "unspecified"),
            "run_id": str(run_id),
            "parent_run_id": str(parent_run_id) if parent_run_id else context.get("parent_run_id"),
            "model": summary["model_name"],
            "finish_reason": summary["finish_reason"],
            "input_tokens": summary["usage_metadata"].get("input_tokens"),
            "output_tokens": summary["usage_metadata"].get("output_tokens"),
            "total_tokens": summary["usage_metadata"].get("total_tokens"),
            "usage_metadata": summary["usage_metadata"] or None,
            "provider_token_usage": summary["provider_token_usage"] or None,
            "budget_window": self._budget_window,
            "budget_tokens": self._budget_tokens,
            "prompt_preview": context.get("prompt_preview") or "",
            "tags": context.get("tags") or [],
        }
        self._append_entry(entry)

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        context = self._pop_context(run_id)
        timestamp = _now_iso()
        entry = {
            "timestamp": timestamp,
            "status": "error",
            "feature": _value_or_default(context.get("feature"), self._feature),
            "operation": _value_or_default(context.get("operation"), "unspecified"),
            "run_id": str(run_id),
            "parent_run_id": str(parent_run_id) if parent_run_id else context.get("parent_run_id"),
            "model": _value_or_default(context.get("model"), ""),
            "finish_reason": "error",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "usage_metadata": None,
            "provider_token_usage": None,
            "budget_window": self._budget_window,
            "budget_tokens": self._budget_tokens,
            "prompt_preview": context.get("prompt_preview") or "",
            "tags": context.get("tags") or [],
            "error_type": error.__class__.__name__,
            "error": _truncate(_collapse_whitespace(str(error) or error.__class__.__name__), limit=320),
        }
        self._append_entry(entry)

    def _store_context(
        self,
        *,
        run_id: UUID,
        serialized: dict[str, Any],
        parent_run_id: UUID | None,
        tags: list[str] | None,
        metadata: dict[str, Any] | None,
        prompt_preview: str,
    ) -> None:
        metadata = metadata or {}
        context = {
            "feature": _string_or_none(metadata.get("ai_feature")) or self._feature,
            "operation": _string_or_none(metadata.get("ai_operation")),
            "model": _string_or_none(metadata.get("ls_model_name")) or _serialized_model_name(serialized),
            "parent_run_id": str(parent_run_id) if parent_run_id else None,
            "tags": [str(tag) for tag in (tags or []) if tag],
            "prompt_preview": prompt_preview,
        }
        with self._contexts_lock:
            self._contexts[str(run_id)] = context

    def _pop_context(self, run_id: UUID) -> dict[str, Any]:
        with self._contexts_lock:
            return self._contexts.pop(str(run_id), {})

    def _append_entry(self, entry: dict[str, Any]) -> None:
        report_path = self._report_path(entry["timestamp"])
        self._report_dir.mkdir(parents=True, exist_ok=True)
        with _REPORT_LOCK:
            period_total_before = _read_period_total_tokens(report_path)
            total_tokens = _safe_int(entry.get("total_tokens")) or 0
            period_total_after = period_total_before + total_tokens
            entry["period_total_tokens"] = period_total_after
            entry["remaining_tokens"] = (
                max(self._budget_tokens - period_total_after, 0)
                if self._budget_tokens is not None
                else None
            )
            with report_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False))
                handle.write("\n")

    def _report_path(self, timestamp: str) -> Path:
        dt = _parse_iso_timestamp(timestamp)
        if self._budget_window == "daily":
            period_key = dt.strftime("%Y-%m-%d")
        elif self._budget_window == "all_time":
            period_key = "all-time"
        else:
            period_key = dt.strftime("%Y-%m")
        return self._report_dir / f"{period_key}.txt"


def _extract_response_summary(response: LLMResult) -> dict[str, Any]:
    llm_output = response.llm_output if isinstance(response.llm_output, dict) else {}
    provider_usage = llm_output.get("token_usage") if isinstance(llm_output.get("token_usage"), dict) else {}
    usage_metadata = _normalize_usage_metadata(None)
    model_name = _string_or_none(llm_output.get("model_name")) or ""
    finish_reason = ""

    for generation_group in response.generations or []:
        for generation in generation_group or []:
            generation_info = getattr(generation, "generation_info", None) or {}
            if not finish_reason:
                finish_reason = _string_or_none(generation_info.get("finish_reason")) or finish_reason
            message = getattr(generation, "message", None)
            if message is None:
                continue
            raw_usage_metadata = getattr(message, "usage_metadata", None)
            usage_metadata = _normalize_usage_metadata(raw_usage_metadata)
            response_metadata = getattr(message, "response_metadata", None) or {}
            if not provider_usage and isinstance(response_metadata.get("token_usage"), dict):
                provider_usage = dict(response_metadata["token_usage"])
            if not model_name:
                model_name = _string_or_none(response_metadata.get("model_name")) or model_name
            if not finish_reason:
                finish_reason = _string_or_none(response_metadata.get("finish_reason")) or finish_reason
            if usage_metadata.get("total_tokens") is not None:
                break
        if usage_metadata.get("total_tokens") is not None:
            break

    if usage_metadata.get("total_tokens") is None:
        usage_metadata = _normalize_usage_metadata(provider_usage)

    return {
        "usage_metadata": usage_metadata,
        "provider_token_usage": provider_usage,
        "model_name": model_name,
        "finish_reason": finish_reason,
    }


def _normalize_usage_metadata(raw_usage: Any) -> dict[str, Any]:
    if not isinstance(raw_usage, dict):
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    input_tokens = _safe_int(raw_usage.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _safe_int(raw_usage.get("prompt_tokens"))

    output_tokens = _safe_int(raw_usage.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _safe_int(raw_usage.get("completion_tokens"))

    total_tokens = _safe_int(raw_usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    normalized: dict[str, Any] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }

    input_details = raw_usage.get("input_token_details") or raw_usage.get("input_tokens_details") or raw_usage.get("prompt_tokens_details")
    output_details = raw_usage.get("output_token_details") or raw_usage.get("output_tokens_details") or raw_usage.get("completion_tokens_details")
    if isinstance(input_details, dict) and input_details:
        normalized["input_token_details"] = dict(input_details)
    if isinstance(output_details, dict) and output_details:
        normalized["output_token_details"] = dict(output_details)
    return normalized


def _read_period_total_tokens(report_path: Path) -> int:
    if not report_path.exists():
        return 0
    total = 0
    with report_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            total += _safe_int(payload.get("total_tokens")) or 0
    return total


def _messages_preview(messages: list[list[BaseMessage]]) -> str:
    preview_lines: list[str] = []
    for message in messages[0] if messages else []:
        role = getattr(message, "type", message.__class__.__name__).lower()
        content = _stringify_content(getattr(message, "content", ""))
        if content:
            preview_lines.append(f"{role}: {content}")
    return _truncate(_collapse_whitespace("\n".join(preview_lines)))


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type"):
                    parts.append(f"[{item.get('type')}]")
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content)


def _serialized_model_name(serialized: dict[str, Any]) -> str:
    if not isinstance(serialized, dict):
        return ""
    model_name = _string_or_none(serialized.get("model_name"))
    if model_name:
        return model_name
    kwargs = serialized.get("kwargs")
    if isinstance(kwargs, dict):
        return _string_or_none(kwargs.get("model_name")) or _string_or_none(kwargs.get("model")) or ""
    return ""


def _parse_iso_timestamp(timestamp: str) -> datetime:
    normalized = str(timestamp or "").strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return datetime.now(timezone.utc)


def _tagify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-") or "unknown"


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _truncate(value: str, *, limit: int = _PREVIEW_LIMIT) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)].rstrip()}..."


def _safe_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _value_or_default(value: Any, default: str) -> str:
    return _string_or_none(value) or default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
