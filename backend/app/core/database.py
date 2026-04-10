from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Iterator

from .exceptions import ConfigurationError
from .security import utc_now_iso


PLAN_SEED_DATA = [
    {
        "code": "starter",
        "name": "Starter",
        "description": "Para sellers que recien empiezan a ordenar su operacion.",
        "price_cents": 2900,
        "currency": "USD",
        "price_label": "US$29/mes",
        "badge": None,
        "is_recommended": False,
        "sort_order": 10,
        "features": [
            "Panel unificado",
            "Preguntas y reclamos",
            "Reply Assistant",
            "Listing Doctor inicial",
        ],
    },
    {
        "code": "growth",
        "name": "Growth",
        "description": "Plan recomendado para sellers que ya venden y quieren escalar mejor.",
        "price_cents": 7900,
        "currency": "USD",
        "price_label": "US$79/mes",
        "badge": "Mas elegido",
        "is_recommended": True,
        "sort_order": 20,
        "features": [
            "Todo Starter",
            "Reply Assistant ilimitado",
            "Listing Doctor completo",
            "Copywriter con contexto",
        ],
    },
    {
        "code": "scale",
        "name": "Scale",
        "description": "Para agencias, marcas y operaciones multi-cuenta.",
        "price_cents": 14900,
        "currency": "USD",
        "price_label": "US$149/mes",
        "badge": "Para agencias",
        "is_recommended": False,
        "sort_order": 30,
        "features": [
            "Todo Growth",
            "Multi-cuenta",
            "Reportes avanzados",
            "Soporte prioritario",
        ],
    },
]

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS workspaces (
        id UUID PRIMARY KEY,
        slug TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id UUID PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        password_salt TEXT,
        password_scheme TEXT NOT NULL DEFAULT 'argon2id',
        is_first_visit BOOLEAN NOT NULL DEFAULT TRUE,
        default_account_key TEXT,
        primary_workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        last_login_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_members (
        id UUID PRIMARY KEY,
        workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        is_owner BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE (workspace_id, user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_workspace_members_user_id ON workspace_members(user_id)",
    """
    CREATE TABLE IF NOT EXISTS subscription_plans (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        currency TEXT NOT NULL,
        price_label TEXT NOT NULL,
        badge TEXT,
        is_recommended BOOLEAN NOT NULL DEFAULT FALSE,
        is_public BOOLEAN NOT NULL DEFAULT TRUE,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        sort_order INTEGER NOT NULL DEFAULT 0,
        entitlements JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workspace_subscriptions (
        id UUID PRIMARY KEY,
        workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        plan_code TEXT REFERENCES subscription_plans(code),
        status TEXT NOT NULL,
        source TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ,
        cancelled_at TIMESTAMPTZ,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_workspace_subscriptions_workspace_status
    ON workspace_subscriptions(workspace_id, status, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS auth_sessions (
        id UUID PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        created_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        last_seen_at TIMESTAMPTZ NOT NULL,
        user_agent TEXT,
        ip_address TEXT,
        rotated_from_session_id UUID REFERENCES auth_sessions(id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at)",
    """
    CREATE TABLE IF NOT EXISTS ml_accounts (
        id UUID PRIMARY KEY,
        workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        linked_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        account_key TEXT NOT NULL,
        label TEXT NOT NULL,
        ml_user_id BIGINT,
        nickname TEXT,
        site_id TEXT,
        access_token_encrypted TEXT NOT NULL,
        refresh_token_encrypted TEXT,
        scope TEXT,
        source TEXT NOT NULL DEFAULT 'oauth',
        created_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE (workspace_id, account_key),
        UNIQUE (workspace_id, ml_user_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_ml_accounts_workspace_id ON ml_accounts(workspace_id)",
    """
    CREATE TABLE IF NOT EXISTS oauth_states (
        state TEXT PRIMARY KEY,
        user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        requested_account_key TEXT,
        requested_label TEXT,
        code_verifier TEXT,
        created_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_oauth_states_user_id ON oauth_states(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_oauth_states_expires_at ON oauth_states(expires_at)",
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id UUID PRIMARY KEY,
        workspace_id UUID REFERENCES workspaces(id) ON DELETE SET NULL,
        user_id UUID REFERENCES users(id) ON DELETE SET NULL,
        event_type TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'info',
        entity_type TEXT,
        entity_id TEXT,
        ip_address TEXT,
        user_agent TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_workspace_id ON audit_logs(workspace_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS idempotency_keys (
        id UUID PRIMARY KEY,
        workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
        request_key TEXT NOT NULL,
        action TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        response_payload JSONB,
        status_code INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        expires_at TIMESTAMPTZ,
        UNIQUE (workspace_id, request_key, action)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_idempotency_keys_workspace_id ON idempotency_keys(workspace_id, created_at DESC)",
]


@dataclass
class DatabaseSession:
    _connection: Any

    def execute(self, query: str, params: tuple[Any, ...] | list[Any] | None = None) -> Any:
        return self._connection.execute(self._translate_query(query), params or ())

    def fetchone(self, query: str, params: tuple[Any, ...] | list[Any] | None = None) -> dict[str, Any] | None:
        return self.execute(query, params).fetchone()

    def fetchall(self, query: str, params: tuple[Any, ...] | list[Any] | None = None) -> list[dict[str, Any]]:
        return list(self.execute(query, params).fetchall())

    def scalar(self, query: str, params: tuple[Any, ...] | list[Any] | None = None) -> Any:
        row = self.execute(query, params).fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            return next(iter(row.values()))
        return row[0]

    @staticmethod
    def _translate_query(query: str) -> str:
        return query.replace("?", "%s")


class Database:
    def __init__(self, url: str) -> None:
        self._url = url.strip()

    @property
    def url(self) -> str:
        return self._url

    def initialize(self) -> None:
        if not self._url:
            raise ConfigurationError(
                "APP_DATABASE_URL es obligatorio. Configura una conexion PostgreSQL antes de iniciar Kaizen Flow.",
            )
        with self.connect() as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            self._seed_subscription_plans(connection)

    def _seed_subscription_plans(self, connection: DatabaseSession) -> None:
        now = utc_now_iso()
        for plan in PLAN_SEED_DATA:
            entitlements = {
                "all_features_enabled": True,
                "plan_code": plan["code"],
                "feature_flags": {"full_product_access": True},
                "landing_features": plan["features"],
            }
            connection.execute(
                """
                INSERT INTO subscription_plans (
                    code, name, description, price_cents, currency, price_label, badge,
                    is_recommended, is_public, is_active, sort_order, entitlements, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, TRUE, TRUE, ?, CAST(? AS JSONB), ?, ?)
                ON CONFLICT (code) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    price_cents = EXCLUDED.price_cents,
                    currency = EXCLUDED.currency,
                    price_label = EXCLUDED.price_label,
                    badge = EXCLUDED.badge,
                    is_recommended = EXCLUDED.is_recommended,
                    sort_order = EXCLUDED.sort_order,
                    entitlements = EXCLUDED.entitlements,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    plan["code"],
                    plan["name"],
                    plan["description"],
                    plan["price_cents"],
                    plan["currency"],
                    plan["price_label"],
                    plan["badge"],
                    plan["is_recommended"],
                    plan["sort_order"],
                    json.dumps(entitlements, ensure_ascii=True),
                    now,
                    now,
                ),
            )

    @contextmanager
    def connect(self) -> Iterator[DatabaseSession]:
        psycopg_module = self._load_psycopg()
        dict_row = import_module("psycopg.rows").dict_row
        connection = psycopg_module.connect(self._url, row_factory=dict_row)
        wrapped = DatabaseSession(connection)
        try:
            yield wrapped
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _load_psycopg() -> Any:
        try:
            return import_module("psycopg")
        except ModuleNotFoundError as exc:
            raise ConfigurationError(
                "psycopg no esta instalado. Instala las dependencias backend antes de usar PostgreSQL.",
            ) from exc

    @staticmethod
    def is_unique_violation(exc: Exception) -> bool:
        message = str(exc).lower()
        return exc.__class__.__name__ == "UniqueViolation" or "duplicate key value" in message

    @staticmethod
    def is_foreign_key_violation(exc: Exception) -> bool:
        message = str(exc).lower()
        return exc.__class__.__name__ == "ForeignKeyViolation" or "foreign key constraint" in message
