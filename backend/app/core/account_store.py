from __future__ import annotations

import re
import sqlite3
from threading import Lock

from .database import Database
from .exceptions import AccountInactiveError, NotFoundError
from .security import utc_now_iso
from .settings import AccountCredentials


def _slugify_account_key(text: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return normalized[:64] or "mercadolibre"


class AccountStore:
    def __init__(self, database: Database, user_id: int, default_account: str | None = None) -> None:
        self._database = database
        self._user_id = user_id
        self._default_account = default_account
        self._lock = Lock()

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def default_account(self) -> str | None:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT default_account_key FROM users WHERE id = ?",
                (self._user_id,),
            ).fetchone()
        value = str(row["default_account_key"]).strip() if row and row["default_account_key"] else None
        if value:
            return value
        return self._default_account

    def list_accounts(self) -> list[AccountCredentials]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT account_key, label, access_token, refresh_token, scope, ml_user_id, source, is_active
                FROM ml_accounts
                WHERE user_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (self._user_id,),
            ).fetchall()
        return [self._row_to_account(row) for row in rows]

    def has_account(self, account_key: str) -> bool:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM ml_accounts WHERE user_id = ? AND account_key = ?",
                (self._user_id, account_key),
            ).fetchone()
        return row is not None

    def resolve_account_key(self, account_key: str | None) -> str:
        if account_key:
            if not self.has_account(account_key):
                raise NotFoundError(f"The account '{account_key}' is not linked to this user.")
            return account_key

        default_account = self.default_account
        if default_account and self.has_account(default_account):
            return default_account

        accounts = self.list_accounts()
        if accounts:
            return accounts[0].key

        raise NotFoundError("No Mercado Libre accounts are linked to this user.")

    def get_account(self, account_key: str | None = None) -> AccountCredentials:
        resolved_key = self.resolve_account_key(account_key)
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT account_key, label, access_token, refresh_token, scope, ml_user_id, source, is_active
                FROM ml_accounts
                WHERE user_id = ? AND account_key = ?
                """,
                (self._user_id, resolved_key),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"The account '{resolved_key}' is not linked to this user.")
        return self._row_to_account(row)

    def set_default_account(self, account_key: str) -> None:
        resolved_key = self.resolve_account_key(account_key)
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE users SET default_account_key = ?, updated_at = ? WHERE id = ?",
                (resolved_key, utc_now_iso(), self._user_id),
            )
        self._default_account = resolved_key

    def resolve_active_account_key(self, account_key: str | None = None) -> str:
        if account_key:
            account = self.get_account(account_key)
            self._ensure_account_is_active(account)
            return account.key

        default_account = self.default_account
        if default_account and self.has_account(default_account):
            default_credentials = self.get_account(default_account)
            if default_credentials.is_active:
                return default_credentials.key

        accounts = self.list_accounts()
        first_active = next((account for account in accounts if account.is_active), None)
        if first_active is not None:
            return first_active.key

        if accounts:
            self._raise_inactive_account(accounts[0])

        raise NotFoundError("No Mercado Libre accounts are linked to this user.")

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
            row = connection.execute(
                """
                SELECT label, refresh_token, scope, ml_user_id, source
                FROM ml_accounts
                WHERE user_id = ? AND account_key = ?
                """,
                (self._user_id, account_key),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"The account '{account_key}' is not linked to this user.")

            connection.execute(
                """
                UPDATE ml_accounts
                SET access_token = ?, refresh_token = ?, scope = ?, ml_user_id = ?, updated_at = ?
                WHERE user_id = ? AND account_key = ?
                """,
                (
                    access_token,
                    refresh_token or row["refresh_token"],
                    scope or row["scope"],
                    user_id or row["ml_user_id"],
                    utc_now_iso(),
                    self._user_id,
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
        is_active_for_new: bool = False,
    ) -> AccountCredentials:
        with self._lock, self._database.connect() as connection:
            now = utc_now_iso()
            existing = connection.execute(
                """
                SELECT account_key
                FROM ml_accounts
                WHERE user_id = ? AND (ml_user_id = ? OR account_key = ?)
                ORDER BY id DESC
                LIMIT 1
                """,
                (self._user_id, ml_user_id, requested_key or ""),
            ).fetchone()

            resolved_key = existing["account_key"] if existing else self._resolve_unique_account_key(connection, requested_key, nickname, label, ml_user_id)

            if existing:
                connection.execute(
                    """
                    UPDATE ml_accounts
                    SET label = ?, nickname = ?, site_id = ?, access_token = ?, refresh_token = ?, scope = ?, source = ?, ml_user_id = ?, updated_at = ?
                    WHERE user_id = ? AND account_key = ?
                    """,
                    (
                        label,
                        nickname,
                        site_id,
                        access_token,
                        refresh_token,
                        scope,
                        source,
                        ml_user_id,
                        now,
                        self._user_id,
                        resolved_key,
                    ),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO ml_accounts (
                        user_id, account_key, label, ml_user_id, nickname, site_id,
                        access_token, refresh_token, scope, source, is_active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._user_id,
                        resolved_key,
                        label,
                        ml_user_id,
                        nickname,
                        site_id,
                        access_token,
                        refresh_token,
                        scope,
                        source,
                        1 if is_active_for_new else 0,
                        now,
                        now,
                    ),
                )

            user_row = connection.execute(
                "SELECT default_account_key FROM users WHERE id = ?",
                (self._user_id,),
            ).fetchone()
            if user_row and not user_row["default_account_key"]:
                connection.execute(
                    "UPDATE users SET default_account_key = ?, updated_at = ? WHERE id = ?",
                    (resolved_key, now, self._user_id),
                )
                self._default_account = resolved_key

        return self.get_account(resolved_key)

    def _resolve_unique_account_key(
        self,
        connection: sqlite3.Connection,
        requested_key: str | None,
        nickname: str | None,
        label: str,
        ml_user_id: int,
    ) -> str:
        base_key = _slugify_account_key(requested_key or nickname or label or str(ml_user_id))
        candidate = base_key
        suffix = 2
        while connection.execute(
            "SELECT 1 FROM ml_accounts WHERE user_id = ? AND account_key = ?",
            (self._user_id, candidate),
        ).fetchone():
            candidate = f"{base_key}_{suffix}"
            suffix += 1
        return candidate

    def _row_to_account(self, row: sqlite3.Row) -> AccountCredentials:
        return AccountCredentials(
            key=str(row["account_key"]),
            label=str(row["label"]),
            access_token=str(row["access_token"]),
            refresh_token=str(row["refresh_token"]) if row["refresh_token"] else None,
            scope=str(row["scope"]) if row["scope"] else None,
            user_id=int(row["ml_user_id"]) if row["ml_user_id"] is not None else None,
            source=str(row["source"] or "oauth"),
            is_active=bool(row["is_active"]) if "is_active" in row.keys() else True,
        )

    def _ensure_account_is_active(self, account: AccountCredentials) -> None:
        if account.is_active:
            return
        self._raise_inactive_account(account)

    def _raise_inactive_account(self, account: AccountCredentials) -> None:
        raise AccountInactiveError(
            "La cuenta está vinculada, pero su membresía está inactiva. Activala para acceder al panel.",
            details={
                "account_key": account.key,
                "account_label": account.label,
                "is_active": account.is_active,
            },
        )
