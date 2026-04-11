from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.plan_catalog import DEFAULT_PLAN_CATALOG, DEFAULT_PLAN_CODE
from app.core.security import TokenCipher, add_hours, normalize_username, utc_now_iso


AUTH_THROTTLE_STALE_DAYS = 30


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    username TEXT,
    username_normalized TEXT,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    is_first_visit INTEGER NOT NULL DEFAULT 1,
    default_account_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    user_agent TEXT,
    ip_address TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_sessions_expires_at ON user_sessions(expires_at);

CREATE TABLE IF NOT EXISTS ml_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    account_key TEXT NOT NULL,
    label TEXT NOT NULL,
    ml_user_id INTEGER,
    nickname TEXT,
    site_id TEXT,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    scope TEXT,
    source TEXT NOT NULL DEFAULT 'oauth',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (user_id, account_key),
    UNIQUE (user_id, ml_user_id)
);

CREATE INDEX IF NOT EXISTS idx_ml_accounts_user_id ON ml_accounts(user_id);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    requested_account_key TEXT,
    requested_label TEXT,
    return_origin TEXT,
    code_verifier TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_oauth_states_user_id ON oauth_states(user_id);
CREATE INDEX IF NOT EXISTS idx_oauth_states_expires_at ON oauth_states(expires_at);

CREATE TABLE IF NOT EXISTS auth_throttle_buckets (
    scope TEXT NOT NULL,
    bucket_key TEXT NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT NOT NULL,
    last_failure_at TEXT,
    next_allowed_at TEXT,
    blocked_until TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, bucket_key)
);

CREATE INDEX IF NOT EXISTS idx_auth_throttle_buckets_scope_next_allowed
ON auth_throttle_buckets(scope, next_allowed_at);
CREATE INDEX IF NOT EXISTS idx_auth_throttle_buckets_scope_blocked_until
ON auth_throttle_buckets(scope, blocked_until);

CREATE TABLE IF NOT EXISTS plans (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    headline TEXT NOT NULL,
    description TEXT NOT NULL,
    price_monthly INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    max_accounts INTEGER NOT NULL DEFAULT 1,
    reply_assistant_limit INTEGER,
    listing_doctor_limit INTEGER,
    features_json TEXT NOT NULL DEFAULT '[]',
    sort_order INTEGER NOT NULL DEFAULT 0,
    is_public INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_plan_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan_code TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'selected',
    source TEXT NOT NULL DEFAULT 'self_service',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    selected_from TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (plan_code) REFERENCES plans(code),
    CHECK (status IN ('selected', 'active', 'canceled', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_user_plan_subscriptions_user_id ON user_plan_subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_plan_subscriptions_plan_code ON user_plan_subscriptions(plan_code);

CREATE TABLE IF NOT EXISTS user_plan_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subscription_id INTEGER,
    plan_code TEXT,
    event_type TEXT NOT NULL,
    source TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (subscription_id) REFERENCES user_plan_subscriptions(id) ON DELETE SET NULL,
    FOREIGN KEY (plan_code) REFERENCES plans(code)
);

CREATE INDEX IF NOT EXISTS idx_user_plan_events_user_id ON user_plan_events(user_id);
"""


class Database:
    def __init__(self, path: Path, *, token_encryption_secret: str | None = None) -> None:
        self._path = Path(path)
        self._token_cipher = TokenCipher(token_encryption_secret)

    @property
    def path(self) -> Path:
        return self._path

    def initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._apply_migrations(connection)
            self._encrypt_plaintext_ml_tokens(connection)

    def _apply_migrations(self, connection: sqlite3.Connection) -> None:
        if not self._column_exists(connection, "users", "is_first_visit"):
            connection.execute(
                "ALTER TABLE users ADD COLUMN is_first_visit INTEGER NOT NULL DEFAULT 1"
            )
            connection.execute("UPDATE users SET is_first_visit = 0")

        if not self._column_exists(connection, "users", "username"):
            connection.execute("ALTER TABLE users ADD COLUMN username TEXT")

        if not self._column_exists(connection, "users", "username_normalized"):
            connection.execute("ALTER TABLE users ADD COLUMN username_normalized TEXT")

        if not self._column_exists(connection, "ml_accounts", "is_active"):
            connection.execute(
                "ALTER TABLE ml_accounts ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1"
            )

        if not self._column_exists(connection, "oauth_states", "return_origin"):
            connection.execute("ALTER TABLE oauth_states ADD COLUMN return_origin TEXT")

        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_normalized ON users(lower(email))"
        )
        self._backfill_usernames(connection)
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_normalized ON users(username_normalized)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_user_plan_subscriptions_current "
            "ON user_plan_subscriptions(user_id) WHERE ended_at IS NULL"
        )
        self._seed_default_plans(connection)
        self._ensure_current_plan_for_existing_users(connection)
        self._cleanup_stale_auth_throttle_buckets(connection)

    def _encrypt_plaintext_ml_tokens(self, connection: sqlite3.Connection) -> None:
        if not self._token_cipher.enabled:
            return

        rows = connection.execute(
            """
            SELECT id, access_token, refresh_token
            FROM ml_accounts
            WHERE access_token IS NOT NULL
            """
        ).fetchall()

        for row in rows:
            access_token = str(row["access_token"] or "")
            refresh_token = str(row["refresh_token"]) if row["refresh_token"] else None
            encrypted_access_token = self._token_cipher.encrypt(access_token)
            encrypted_refresh_token = self._token_cipher.encrypt(refresh_token)
            if encrypted_access_token == access_token and encrypted_refresh_token == refresh_token:
                continue
            connection.execute(
                """
                UPDATE ml_accounts
                SET access_token = ?, refresh_token = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    encrypted_access_token,
                    encrypted_refresh_token,
                    utc_now_iso(),
                    int(row["id"]),
                ),
            )

    def _cleanup_stale_auth_throttle_buckets(self, connection: sqlite3.Connection) -> None:
        cutoff_iso = add_hours(-(AUTH_THROTTLE_STALE_DAYS * 24))
        connection.execute(
            """
            DELETE FROM auth_throttle_buckets
            WHERE updated_at < ?
            """,
            (cutoff_iso,),
        )

    def _column_exists(
        self,
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
    ) -> bool:
        columns = {
            str(row["name"]).strip().lower()
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        return column_name.strip().lower() in columns

    def _backfill_usernames(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            """
            SELECT id, email, username, username_normalized
            FROM users
            WHERE username IS NULL
               OR trim(username) = ''
               OR username_normalized IS NULL
               OR trim(username_normalized) = ''
            ORDER BY id
            """
        ).fetchall()

        for row in rows:
            user_id = int(row["id"])
            email = str(row["email"] or "")
            current_username = str(row["username"] or "").strip()
            base_username = current_username or email.partition("@")[0] or f"user_{user_id}"
            candidate = normalize_username(base_username) or f"user_{user_id}"
            unique_username = self._ensure_unique_username(
                connection,
                user_id=user_id,
                base_username=candidate,
            )
            connection.execute(
                """
                UPDATE users
                SET username = ?, username_normalized = ?, updated_at = COALESCE(updated_at, ?)
                WHERE id = ?
                """,
                (unique_username, unique_username, utc_now_iso(), user_id),
            )

    def _ensure_unique_username(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: int,
        base_username: str,
    ) -> str:
        normalized_base = normalize_username(base_username) or f"user_{user_id}"
        candidate = normalized_base
        suffix = 1

        while True:
            row = connection.execute(
                """
                SELECT 1
                FROM users
                WHERE username_normalized = ?
                  AND id != ?
                LIMIT 1
                """,
                (candidate, user_id),
            ).fetchone()
            if row is None:
                return candidate

            suffix += 1
            suffix_text = f"_{suffix}"
            trimmed = normalized_base[: max(1, 40 - len(suffix_text))]
            candidate = f"{trimmed}{suffix_text}"

    def _seed_default_plans(self, connection: sqlite3.Connection) -> None:
        now = utc_now_iso()
        for plan in DEFAULT_PLAN_CATALOG:
            connection.execute(
                """
                INSERT INTO plans (
                    code,
                    name,
                    headline,
                    description,
                    price_monthly,
                    currency,
                    max_accounts,
                    reply_assistant_limit,
                    listing_doctor_limit,
                    features_json,
                    sort_order,
                    is_public,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    headline = excluded.headline,
                    description = excluded.description,
                    price_monthly = excluded.price_monthly,
                    currency = excluded.currency,
                    max_accounts = excluded.max_accounts,
                    reply_assistant_limit = excluded.reply_assistant_limit,
                    listing_doctor_limit = excluded.listing_doctor_limit,
                    features_json = excluded.features_json,
                    sort_order = excluded.sort_order,
                    is_public = excluded.is_public,
                    updated_at = excluded.updated_at
                """,
                (
                    plan.code,
                    plan.name,
                    plan.headline,
                    plan.description,
                    plan.price_monthly,
                    plan.currency,
                    plan.max_accounts,
                    plan.reply_assistant_limit,
                    plan.listing_doctor_limit,
                    json.dumps(list(plan.features)),
                    plan.sort_order,
                    now,
                    now,
                ),
            )

    def _ensure_current_plan_for_existing_users(self, connection: sqlite3.Connection) -> None:
        now = utc_now_iso()
        rows = connection.execute(
            """
            SELECT users.id
            FROM users
            LEFT JOIN user_plan_subscriptions current_subscription
              ON current_subscription.user_id = users.id
             AND current_subscription.ended_at IS NULL
            WHERE current_subscription.id IS NULL
            ORDER BY users.id
            """
        ).fetchall()

        for row in rows:
            user_id = int(row["id"])
            cursor = connection.execute(
                """
                INSERT INTO user_plan_subscriptions (
                    user_id,
                    plan_code,
                    status,
                    source,
                    started_at,
                    selected_from,
                    notes,
                    created_at,
                    updated_at
                ) VALUES (?, ?, 'selected', 'migration_default', ?, 'database.initialize', ?, ?, ?)
                """,
                (
                    user_id,
                    DEFAULT_PLAN_CODE,
                    now,
                    "Backfilled during auth and plan migration.",
                    now,
                    now,
                ),
            )
            subscription_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO user_plan_events (
                    user_id,
                    subscription_id,
                    plan_code,
                    event_type,
                    source,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, 'backfilled', 'database.initialize', ?, ?)
                """,
                (
                    user_id,
                    subscription_id,
                    DEFAULT_PLAN_CODE,
                    json.dumps({"reason": "missing_current_plan"}),
                    now,
                ),
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
