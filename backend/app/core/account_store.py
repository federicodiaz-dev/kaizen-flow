from __future__ import annotations

import re
from threading import Lock
from uuid import uuid4

from .database import Database, DatabaseSession
from .exceptions import NotFoundError
from .security import decrypt_secret, encrypt_secret, utc_now_iso
from .settings import AccountCredentials


def _slugify_account_key(text: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return normalized[:64] or "mercadolibre"


class AccountStore:
    def __init__(
        self,
        database: Database,
        *,
        user_id: str,
        workspace_id: str,
        default_account: str | None = None,
        encryption_key: str,
    ) -> None:
        self._database = database
        self._user_id = user_id
        self._workspace_id = workspace_id
        self._default_account = default_account
        self._encryption_key = encryption_key
        self._lock = Lock()

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def default_account(self) -> str | None:
        with self._database.connect() as connection:
            row = connection.fetchone(
                "SELECT default_account_key FROM users WHERE id = ?",
                (self._user_id,),
            )
        value = str(row["default_account_key"]).strip() if row and row["default_account_key"] else None
        if value:
            return value
        return self._default_account

    def list_accounts(self) -> list[AccountCredentials]:
        with self._database.connect() as connection:
            rows = connection.fetchall(
                """
                SELECT account_key, label, access_token_encrypted, refresh_token_encrypted, scope, ml_user_id, source
                FROM ml_accounts
                WHERE workspace_id = ?
                ORDER BY updated_at DESC, created_at DESC
                """,
                (self._workspace_id,),
            )
        return [self._row_to_account(row) for row in rows]

    def has_account(self, account_key: str) -> bool:
        with self._database.connect() as connection:
            row = connection.fetchone(
                "SELECT 1 FROM ml_accounts WHERE workspace_id = ? AND account_key = ?",
                (self._workspace_id, account_key),
            )
        return row is not None

    def resolve_account_key(self, account_key: str | None) -> str:
        if account_key:
            if not self.has_account(account_key):
                raise NotFoundError(f"The account '{account_key}' is not linked to this workspace.")
            return account_key

        default_account = self.default_account
        if default_account and self.has_account(default_account):
            return default_account

        accounts = self.list_accounts()
        if accounts:
            return accounts[0].key

        raise NotFoundError("No Mercado Libre accounts are linked to this workspace.")

    def resolve_active_account_key(self, account_key: str | None = None) -> str:
        return self.resolve_account_key(account_key)

    def get_account(self, account_key: str | None = None) -> AccountCredentials:
        resolved_key = self.resolve_account_key(account_key)
        with self._database.connect() as connection:
            row = connection.fetchone(
                """
                SELECT account_key, label, access_token_encrypted, refresh_token_encrypted, scope, ml_user_id, source
                FROM ml_accounts
                WHERE workspace_id = ? AND account_key = ?
                """,
                (self._workspace_id, resolved_key),
            )
        if row is None:
            raise NotFoundError(f"The account '{resolved_key}' is not linked to this workspace.")
        return self._row_to_account(row)

    def set_default_account(self, account_key: str) -> None:
        resolved_key = self.resolve_account_key(account_key)
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE users SET default_account_key = ?, updated_at = ? WHERE id = ?",
                (resolved_key, utc_now_iso(), self._user_id),
            )
        self._default_account = resolved_key

    def update_account_tokens(
        self,
        account_key: str,
        *,
        access_token: str,
        refresh_token: str | None,
        scope: str | None,
        user_id: int | None,
    ) -> AccountCredentials:
        with self._lock, self._database.connect() as connection:
            row = connection.fetchone(
                """
                SELECT label, refresh_token_encrypted, scope, ml_user_id, source
                FROM ml_accounts
                WHERE workspace_id = ? AND account_key = ?
                """,
                (self._workspace_id, account_key),
            )
            if row is None:
                raise NotFoundError(f"The account '{account_key}' is not linked to this workspace.")

            encrypted_refresh_token = (
                encrypt_secret(refresh_token, self._encryption_key)
                if refresh_token
                else row["refresh_token_encrypted"]
            )

            connection.execute(
                """
                UPDATE ml_accounts
                SET access_token_encrypted = ?, refresh_token_encrypted = ?, scope = ?, ml_user_id = ?, updated_at = ?
                WHERE workspace_id = ? AND account_key = ?
                """,
                (
                    encrypt_secret(access_token, self._encryption_key),
                    encrypted_refresh_token,
                    scope or row["scope"],
                    user_id or row["ml_user_id"],
                    utc_now_iso(),
                    self._workspace_id,
                    account_key,
                ),
            )

        return self.get_account(account_key)

    def upsert_account(
        self,
        *,
        ml_user_id: int,
        label: str,
        access_token: str,
        refresh_token: str | None,
        scope: str | None,
        nickname: str | None = None,
        site_id: str | None = None,
        requested_key: str | None = None,
        source: str = "oauth",
    ) -> AccountCredentials:
        with self._lock, self._database.connect() as connection:
            now = utc_now_iso()
            existing = connection.fetchone(
                """
                SELECT account_key
                FROM ml_accounts
                WHERE workspace_id = ? AND (ml_user_id = ? OR account_key = ?)
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (self._workspace_id, ml_user_id, requested_key or ""),
            )

            resolved_key = (
                str(existing["account_key"])
                if existing
                else self._resolve_unique_account_key(connection, requested_key, nickname, label, ml_user_id)
            )

            if existing:
                connection.execute(
                    """
                    UPDATE ml_accounts
                    SET label = ?, nickname = ?, site_id = ?, access_token_encrypted = ?,
                        refresh_token_encrypted = ?, scope = ?, source = ?, ml_user_id = ?, updated_at = ?
                    WHERE workspace_id = ? AND account_key = ?
                    """,
                    (
                        label,
                        nickname,
                        site_id,
                        encrypt_secret(access_token, self._encryption_key),
                        encrypt_secret(refresh_token, self._encryption_key) if refresh_token else None,
                        scope,
                        source,
                        ml_user_id,
                        now,
                        self._workspace_id,
                        resolved_key,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO ml_accounts (
                        id, workspace_id, linked_user_id, account_key, label, ml_user_id, nickname, site_id,
                        access_token_encrypted, refresh_token_encrypted, scope, source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        self._workspace_id,
                        self._user_id,
                        resolved_key,
                        label,
                        ml_user_id,
                        nickname,
                        site_id,
                        encrypt_secret(access_token, self._encryption_key),
                        encrypt_secret(refresh_token, self._encryption_key) if refresh_token else None,
                        scope,
                        source,
                        now,
                        now,
                    ),
                )

            user_row = connection.fetchone(
                "SELECT default_account_key FROM users WHERE id = ?",
                (self._user_id,),
            )
            if user_row and not user_row["default_account_key"]:
                connection.execute(
                    "UPDATE users SET default_account_key = ?, updated_at = ? WHERE id = ?",
                    (resolved_key, now, self._user_id),
                )
                self._default_account = resolved_key

        return self.get_account(resolved_key)

    def _resolve_unique_account_key(
        self,
        connection: DatabaseSession,
        requested_key: str | None,
        nickname: str | None,
        label: str,
        ml_user_id: int,
    ) -> str:
        base_key = _slugify_account_key(requested_key or nickname or label or str(ml_user_id))
        candidate = base_key
        suffix = 2
        while connection.fetchone(
            "SELECT 1 FROM ml_accounts WHERE workspace_id = ? AND account_key = ?",
            (self._workspace_id, candidate),
        ):
            candidate = f"{base_key}_{suffix}"
            suffix += 1
        return candidate

    def _row_to_account(self, row: dict[str, object]) -> AccountCredentials:
        return AccountCredentials(
            key=str(row["account_key"]),
            label=str(row["label"]),
            access_token=decrypt_secret(str(row["access_token_encrypted"]), self._encryption_key) or "",
            refresh_token=decrypt_secret(str(row["refresh_token_encrypted"]), self._encryption_key)
            if row.get("refresh_token_encrypted")
            else None,
            scope=str(row["scope"]) if row.get("scope") else None,
            user_id=int(row["ml_user_id"]) if row.get("ml_user_id") is not None else None,
            source=str(row.get("source") or "oauth"),
            is_active=True,
        )
