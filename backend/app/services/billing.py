from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.core.audit import record_audit_event
from app.core.database import Database
from app.core.exceptions import BadRequestError, ConflictError
from app.core.security import add_hours, utc_now_iso
from app.schemas.auth import SubscriptionProfile
from app.services.auth import AuthenticatedUser


ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


@dataclass(frozen=True, slots=True)
class CheckoutResult:
    plan_code: str
    plan_name: str
    status: str
    duplicated_request: bool = False


class BillingService:
    def __init__(self, *, database: Database) -> None:
        self._database = database

    def simulate_checkout(
        self,
        *,
        current_user: AuthenticatedUser,
        plan_code: str,
        idempotency_key: str | None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> CheckoutResult:
        normalized_plan_code = plan_code.strip().lower()
        if not normalized_plan_code:
            raise BadRequestError("Selecciona un plan valido.")

        request_hash = hashlib.sha256(normalized_plan_code.encode("utf-8")).hexdigest()
        now = utc_now_iso()
        action = "billing.checkout.simulate"

        with self._database.connect() as connection:
            plan_row = connection.fetchone(
                """
                SELECT code, name
                FROM subscription_plans
                WHERE code = ? AND is_public = TRUE AND is_active = TRUE
                """,
                (normalized_plan_code,),
            )
            if plan_row is None:
                raise BadRequestError("El plan seleccionado no existe o no esta disponible.")

            if idempotency_key:
                idempotency_row = connection.fetchone(
                    """
                    SELECT request_hash
                    FROM idempotency_keys
                    WHERE workspace_id = ? AND request_key = ? AND action = ?
                    """,
                    (current_user.workspace_id, idempotency_key, action),
                )
                if idempotency_row:
                    if str(idempotency_row["request_hash"]) != request_hash:
                        raise ConflictError("La misma clave de idempotencia no puede usarse con otro plan.")
                    return CheckoutResult(
                        plan_code=str(plan_row["code"]),
                        plan_name=str(plan_row["name"]),
                        status="active",
                        duplicated_request=True,
                    )

            active_row = connection.fetchone(
                """
                SELECT id, plan_code, status
                FROM workspace_subscriptions
                WHERE workspace_id = ?
                ORDER BY
                    CASE
                        WHEN status = 'active' THEN 0
                        WHEN status = 'trialing' THEN 1
                        ELSE 2
                    END,
                    updated_at DESC
                LIMIT 1
                """,
                (current_user.workspace_id,),
            )

            if (
                active_row
                and str(active_row.get("status") or "") in ACTIVE_SUBSCRIPTION_STATUSES
                and str(active_row.get("plan_code") or "") == normalized_plan_code
            ):
                if idempotency_key:
                    self._store_idempotency_key(
                        connection=connection,
                        workspace_id=current_user.workspace_id,
                        request_key=idempotency_key,
                        action=action,
                        request_hash=request_hash,
                        payload={"plan_code": normalized_plan_code, "status": "active", "duplicate": True},
                    )
                return CheckoutResult(
                    plan_code=str(plan_row["code"]),
                    plan_name=str(plan_row["name"]),
                    status="active",
                    duplicated_request=True,
                )

            connection.execute(
                """
                UPDATE workspace_subscriptions
                SET status = 'replaced', updated_at = ?, cancelled_at = COALESCE(cancelled_at, ?)
                WHERE workspace_id = ? AND status IN ('active', 'trialing')
                """,
                (now, now, current_user.workspace_id),
            )

            connection.execute(
                """
                INSERT INTO workspace_subscriptions (
                    id, workspace_id, plan_code, status, source, started_at, expires_at,
                    cancelled_at, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, 'active', 'simulated_checkout', ?, NULL, NULL, CAST(? AS JSONB), ?, ?)
                """,
                (
                    str(uuid4()),
                    current_user.workspace_id,
                    normalized_plan_code,
                    now,
                    json.dumps(
                        {
                            "selected_by_user_id": current_user.id,
                            "selected_plan_code": normalized_plan_code,
                            "simulated": True,
                        },
                        ensure_ascii=True,
                    ),
                    now,
                    now,
                ),
            )

            if idempotency_key:
                self._store_idempotency_key(
                    connection=connection,
                    workspace_id=current_user.workspace_id,
                    request_key=idempotency_key,
                    action=action,
                    request_hash=request_hash,
                    payload={"plan_code": normalized_plan_code, "status": "active"},
                )

            record_audit_event(
                self._database,
                event_type="billing.checkout_simulated",
                workspace_id=current_user.workspace_id,
                user_id=current_user.id,
                entity_type="subscription_plan",
                entity_id=normalized_plan_code,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={"plan_code": normalized_plan_code},
                connection=connection,
            )

        return CheckoutResult(
            plan_code=str(plan_row["code"]),
            plan_name=str(plan_row["name"]),
            status="active",
        )

    @staticmethod
    def to_subscription_profile(result: CheckoutResult) -> SubscriptionProfile:
        return SubscriptionProfile(
            status=result.status,
            plan_code=result.plan_code,
            plan_name=result.plan_name,
            started_at=None,
            updated_at=None,
            expires_at=None,
            is_active=result.status in ACTIVE_SUBSCRIPTION_STATUSES,
        )

    def _store_idempotency_key(
        self,
        *,
        connection: Any,
        workspace_id: str,
        request_key: str,
        action: str,
        request_hash: str,
        payload: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        connection.execute(
            """
            INSERT INTO idempotency_keys (
                id, workspace_id, request_key, action, request_hash, response_payload,
                status_code, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, CAST(? AS JSONB), 200, ?, ?)
            ON CONFLICT (workspace_id, request_key, action) DO UPDATE SET
                request_hash = EXCLUDED.request_hash,
                response_payload = EXCLUDED.response_payload,
                status_code = EXCLUDED.status_code,
                expires_at = EXCLUDED.expires_at
            """,
            (
                str(uuid4()),
                workspace_id,
                request_key,
                action,
                request_hash,
                json.dumps(payload, ensure_ascii=True),
                now,
                add_hours(24),
            ),
        )
