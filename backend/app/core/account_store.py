from __future__ import annotations

from dataclasses import replace
from threading import Lock

from .exceptions import ConfigurationError, NotFoundError
from .settings import AccountCredentials


class AccountStore:
    def __init__(self, accounts: dict[str, AccountCredentials], default_account: str) -> None:
        self._accounts = {key: replace(account) for key, account in accounts.items()}
        self._default_account = default_account
        self._lock = Lock()

    @property
    def default_account(self) -> str:
        return self._default_account

    def list_accounts(self) -> list[AccountCredentials]:
        return [replace(account) for account in self._accounts.values()]

    def has_account(self, account_key: str) -> bool:
        return account_key in self._accounts

    def resolve_account_key(self, account_key: str | None) -> str:
        if account_key:
            if account_key not in self._accounts:
                raise NotFoundError(f"The account '{account_key}' is not configured.")
            return account_key

        if self._default_account in self._accounts:
            return self._default_account

        if self._accounts:
            return next(iter(self._accounts))

        raise ConfigurationError("No Mercado Libre accounts are configured.")

    def get_account(self, account_key: str | None = None) -> AccountCredentials:
        resolved_key = self.resolve_account_key(account_key)
        return replace(self._accounts[resolved_key])

    def update_account_tokens(
        self,
        account_key: str,
        *,
        access_token: str,
        refresh_token: str | None,
        scope: str | None,
        user_id: int | None,
    ) -> AccountCredentials:
        with self._lock:
            account = self._accounts[account_key]
            updated = replace(
                account,
                access_token=access_token,
                refresh_token=refresh_token or account.refresh_token,
                scope=scope or account.scope,
                user_id=user_id or account.user_id,
            )
            self._accounts[account_key] = updated
            return replace(updated)
