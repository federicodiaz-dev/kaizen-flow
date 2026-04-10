from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from .database import Database, DatabaseSession
from .security import utc_now_iso


def record_audit_event(
    database: Database,
    *,
    event_type: str,
    workspace_id: str | None = None,
    user_id: str | None = None,
    severity: str = "info",
    entity_type: str | None = None,
    entity_id: str | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
    connection: DatabaseSession | None = None,
) -> None:
    target = connection
    context = None
    if target is None:
        context = database.connect()
        target = context.__enter__()

    try:
        target.execute(
            """
            INSERT INTO audit_logs (
                id, workspace_id, user_id, event_type, severity, entity_type, entity_id,
                ip_address, user_agent, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CAST(? AS JSONB), ?)
            """,
            (
                str(uuid4()),
                workspace_id,
                user_id,
                event_type,
                severity,
                entity_type,
                entity_id,
                ip_address,
                user_agent,
                json.dumps(metadata or {}, ensure_ascii=True),
                utc_now_iso(),
            ),
        )
    finally:
        if context is not None:
            context.__exit__(None, None, None)
