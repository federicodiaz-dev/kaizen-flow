from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import Depends, Header, Query, Request

from app.adapters.claims import ClaimsAdapter
from app.adapters.items import ItemsAdapter
from app.adapters.questions import QuestionsAdapter
from app.clients.mercadolibre import MercadoLibreClient
from app.core.account_store import AccountStore
from app.core.settings import Settings
from app.services.accounts import AccountsService
from app.services.claims import ClaimsService
from app.services.items import ItemsService
from app.services.questions import QuestionsService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_account_store(request: Request) -> AccountStore:
    return request.app.state.account_store


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


def get_ml_client(
    settings: Annotated[Settings, Depends(get_settings)],
    account_store: Annotated[AccountStore, Depends(get_account_store)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> MercadoLibreClient:
    return MercadoLibreClient(http_client=http_client, settings=settings, account_store=account_store)


def get_accounts_service(
    account_store: Annotated[AccountStore, Depends(get_account_store)],
) -> AccountsService:
    return AccountsService(account_store=account_store)


def get_questions_service(
    account_store: Annotated[AccountStore, Depends(get_account_store)],
    client: Annotated[MercadoLibreClient, Depends(get_ml_client)],
) -> QuestionsService:
    return QuestionsService(
        account_store=account_store,
        client=client,
        questions_adapter=QuestionsAdapter(client),
        items_adapter=ItemsAdapter(client),
    )


def get_claims_service(
    account_store: Annotated[AccountStore, Depends(get_account_store)],
    client: Annotated[MercadoLibreClient, Depends(get_ml_client)],
) -> ClaimsService:
    return ClaimsService(account_store=account_store, client=client, claims_adapter=ClaimsAdapter(client))


def get_items_service(
    account_store: Annotated[AccountStore, Depends(get_account_store)],
    client: Annotated[MercadoLibreClient, Depends(get_ml_client)],
) -> ItemsService:
    return ItemsService(account_store=account_store, client=client, items_adapter=ItemsAdapter(client))


def resolve_account(
    account_store: Annotated[AccountStore, Depends(get_account_store)],
    account: str | None = Query(default=None),
    x_kaizen_account: str | None = Header(default=None, alias="X-Kaizen-Account"),
) -> str:
    return account_store.resolve_account_key(account or x_kaizen_account)
