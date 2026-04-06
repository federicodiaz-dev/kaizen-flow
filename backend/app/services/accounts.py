from __future__ import annotations

from app.core.account_store import AccountStore
from app.schemas.accounts import AccountSummary, AccountsResponse, DefaultAccountResponse


class AccountsService:
    def __init__(self, account_store: AccountStore) -> None:
        self._account_store = account_store

    def list_accounts(self) -> AccountsResponse:
        items = [
            AccountSummary(
                key=account.key,
                label=account.label,
                source=account.source,
                user_id=account.user_id,
                scope=account.scope,
                is_default=account.key == self._account_store.default_account,
                is_active=account.is_active,
            )
            for account in self._account_store.list_accounts()
        ]
        return AccountsResponse(default_account=self._account_store.default_account, items=items)

    def set_default_account(self, account_key: str) -> DefaultAccountResponse:
        self._account_store.set_default_account(account_key)
        return DefaultAccountResponse(default_account=account_key)
