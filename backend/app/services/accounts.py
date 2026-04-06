from __future__ import annotations

from app.core.account_store import AccountStore
from app.schemas.accounts import AccountSummary, AccountsResponse


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
            )
            for account in self._account_store.list_accounts()
        ]
        return AccountsResponse(default_account=self._account_store.default_account, items=items)
