from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_THREAD_TITLE = "Nueva conversacion"
TITLE_LIMIT = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char)).lower()


def _clean_preview(text: str, limit: int = 96) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3].rstrip()}..."


def fallback_thread_title(text: str) -> str:
    cleaned = re.sub(r"[^\w\s/+()-]", " ", text)
    lowered = _normalize_text(cleaned)

    keyword_titles = {
        "reclamo": "Analisis de reclamo",
        "claim": "Claim review",
        "pregunta": "Preguntas de cuenta",
        "question": "Question support",
        "mercado": "Analisis de mercado",
        "trend": "Market trends",
        "tendencia": "Tendencias ML",
        "producto": "Ideas de productos",
        "publicacion": "Revision de publicaciones",
        "titulo": "Mejorar titulos",
        "descripcion": "Mejorar descripcion",
        "venta": "Estrategia de ventas",
    }
    for keyword, title in keyword_titles.items():
        if keyword in lowered:
            return title

    candidate = " ".join(cleaned.split()[:6]).strip()
    if not candidate:
        return DEFAULT_THREAD_TITLE

    candidate = candidate[0].upper() + candidate[1:]
    return candidate[:TITLE_LIMIT].strip()


@dataclass(slots=True)
class MemorySnapshot:
    chat_history: str


@dataclass(slots=True)
class StoredMessage:
    role: str
    content: str
    created_at: str
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not self.metadata:
            payload.pop("metadata", None)
        return payload


@dataclass(slots=True)
class ThreadRecord:
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[StoredMessage]

    @property
    def last_message_preview(self) -> str:
        if not self.messages:
            return "Nueva conversacion lista para empezar."
        return _clean_preview(self.messages[-1].content)

    @property
    def message_count(self) -> int:
        return len(self.messages)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
            "last_message_preview": self.last_message_preview,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_summary_dict()
        payload["messages"] = [message.to_dict() for message in self.messages]
        return payload


class JsonAgentMemoryStore:
    def __init__(self, base_dir: Path) -> None:
        self._base_dir = Path(base_dir)
        self._threads_dir = self._base_dir / "threads"
        self._threads_dir.mkdir(parents=True, exist_ok=True)

    def _thread_path(self, thread_id: str) -> Path:
        return self._threads_dir / f"{thread_id}.json"

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _normalize_payload(self, thread_id: str, payload: Any, path: Path) -> dict[str, Any]:
        file_time = (
            datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
            if path.exists()
            else _now_iso()
        )
        if not isinstance(payload, dict):
            payload = {}

        raw_messages = payload.get("messages", [])
        if not isinstance(raw_messages, list):
            raw_messages = []

        messages: list[dict[str, Any]] = []
        for raw_message in raw_messages[-100:]:
            if not isinstance(raw_message, dict):
                continue
            role = str(raw_message.get("role", "assistant")).strip() or "assistant"
            content = str(raw_message.get("content", "")).strip()
            metadata = raw_message.get("metadata")
            if not content:
                continue
            messages.append(
                {
                    "role": role,
                    "content": content,
                    "created_at": str(raw_message.get("created_at", file_time)),
                    "metadata": metadata if isinstance(metadata, dict) else None,
                }
            )

        title = str(payload.get("title", "")).strip()
        if not title:
            first_user_message = next(
                (message["content"] for message in messages if message["role"] == "user"),
                "",
            )
            title = fallback_thread_title(first_user_message)

        created_at = str(payload.get("created_at", file_time))
        updated_at = str(
            payload.get(
                "updated_at",
                messages[-1]["created_at"] if messages else created_at,
            )
        )

        return {
            "thread_id": thread_id,
            "title": title[:TITLE_LIMIT] or DEFAULT_THREAD_TITLE,
            "created_at": created_at,
            "updated_at": updated_at,
            "messages": messages,
        }

    def _load_thread_payload(self, thread_id: str) -> dict[str, Any]:
        path = self._thread_path(thread_id)
        raw_payload = self._read_json(path, {})
        normalized = self._normalize_payload(thread_id, raw_payload, path)
        if normalized != raw_payload:
            self._write_json(path, normalized)
        return normalized

    def _payload_to_record(self, payload: dict[str, Any]) -> ThreadRecord:
        return ThreadRecord(
            thread_id=payload["thread_id"],
            title=payload["title"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            messages=[
                StoredMessage(
                    role=message["role"],
                    content=message["content"],
                    created_at=message["created_at"],
                    metadata=message.get("metadata"),
                )
                for message in payload.get("messages", [])
            ],
        )

    def generate_thread_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"agent-{timestamp}-{uuid4().hex[:6]}"

    def create_thread(self, title: str = DEFAULT_THREAD_TITLE, thread_id: str | None = None) -> ThreadRecord:
        thread_id = thread_id or self.generate_thread_id()
        path = self._thread_path(thread_id)
        if path.exists():
            return self.get_thread(thread_id)

        timestamp = _now_iso()
        payload = {
            "thread_id": thread_id,
            "title": (title or DEFAULT_THREAD_TITLE)[:TITLE_LIMIT],
            "created_at": timestamp,
            "updated_at": timestamp,
            "messages": [],
        }
        self._write_json(path, payload)
        return self._payload_to_record(payload)

    def ensure_thread(self, thread_id: str) -> ThreadRecord:
        path = self._thread_path(thread_id)
        if not path.exists():
            return self.create_thread(thread_id=thread_id)
        return self.get_thread(thread_id)

    def get_thread(self, thread_id: str) -> ThreadRecord:
        return self._payload_to_record(self._load_thread_payload(thread_id))

    def list_threads(self) -> list[ThreadRecord]:
        records: list[ThreadRecord] = []
        for path in sorted(self._threads_dir.glob("*.json")):
            records.append(self.get_thread(path.stem))
        return sorted(records, key=lambda record: record.updated_at, reverse=True)

    def set_title(self, thread_id: str, title: str) -> ThreadRecord:
        payload = self._load_thread_payload(thread_id)
        payload["title"] = (title or DEFAULT_THREAD_TITLE)[:TITLE_LIMIT] or DEFAULT_THREAD_TITLE
        payload["updated_at"] = _now_iso()
        self._write_json(self._thread_path(thread_id), payload)
        return self._payload_to_record(payload)

    def load_snapshot(self, thread_id: str, limit: int = 8) -> MemorySnapshot:
        thread = self.ensure_thread(thread_id)
        history_lines = [f"{message.role.capitalize()}: {message.content}" for message in thread.messages[-limit:]]
        return MemorySnapshot(chat_history="\n".join(history_lines) or "No prior conversation in this thread.")

    def append_turn(
        self,
        thread_id: str,
        user_input: str,
        assistant_output: str,
        *,
        user_metadata: dict[str, Any] | None = None,
        assistant_metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = self._load_thread_payload(thread_id)
        user_timestamp = _now_iso()
        assistant_timestamp = _now_iso()
        payload.setdefault("messages", [])
        payload["messages"].append(
            {
                "role": "user",
                "content": user_input.strip(),
                "created_at": user_timestamp,
                "metadata": user_metadata or None,
            }
        )
        payload["messages"].append(
            {
                "role": "assistant",
                "content": assistant_output.strip(),
                "created_at": assistant_timestamp,
                "metadata": assistant_metadata or None,
            }
        )
        payload["messages"] = payload["messages"][-100:]
        payload["updated_at"] = assistant_timestamp
        self._write_json(self._thread_path(thread_id), payload)
