from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import Depends, Header, Query, Request

from app.agents.service import BusinessAssistantService
from app.adapters.claims import ClaimsAdapter
from app.adapters.items import ItemsAdapter
from app.adapters.questions import QuestionsAdapter
from app.clients.mercadolibre import MercadoLibreClient
from app.core.account_store import AccountStore
from app.core.settings import Settings, get_settings as load_core_settings
from app.services.accounts import AccountsService
from app.services.claims import ClaimsService
from app.services.items import ItemsService
from app.services.questions import QuestionsService


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        settings = load_core_settings()
        request.app.state.settings = settings
    return settings


def get_account_store(request: Request) -> AccountStore:
    account_store = getattr(request.app.state, "account_store", None)
    if account_store is None:
        settings = get_settings(request)
        account_store = AccountStore(settings.accounts, settings.default_account)
        request.app.state.account_store = account_store
    return account_store


def get_http_client(request: Request) -> httpx.AsyncClient:
    http_client = getattr(request.app.state, "http_client", None)
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        request.app.state.http_client = http_client
    return http_client


def get_agents_service(request: Request) -> BusinessAssistantService:
    service = getattr(request.app.state, "agents_service", None)
    if service is None:
        service = BusinessAssistantService(
            settings=get_settings(request),
            account_store=get_account_store(request),
            http_client=get_http_client(request),
        )
        request.app.state.agents_service = service
    return service


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


def get_copywriter_service(request: Request) -> "CopywriterService":
    from app.services.copywriter import CopywriterService as _CopywriterService

    service = getattr(request.app.state, "copywriter_service", None)
    if service is None:
        service = _CopywriterService()
        request.app.state.copywriter_service = service
    return service


def get_reply_assistant_service(request: Request) -> "ReplyAssistantService":
    from app.services.reply_assistant import ReplyAssistantService as _ReplyAssistantService

    service = getattr(request.app.state, "reply_assistant_service", None)
    if service is None:
        settings = get_settings(request)
        account_store = get_account_store(request)
        http_client = get_http_client(request)
        ml_client = MercadoLibreClient(http_client=http_client, settings=settings, account_store=account_store)

        service = _ReplyAssistantService(
            questions_service=QuestionsService(
                account_store=account_store,
                client=ml_client,
                questions_adapter=QuestionsAdapter(ml_client),
                items_adapter=ItemsAdapter(ml_client),
            ),
            claims_service=ClaimsService(
                account_store=account_store,
                client=ml_client,
                claims_adapter=ClaimsAdapter(ml_client),
            ),
            items_service=ItemsService(
                account_store=account_store,
                client=ml_client,
                items_adapter=ItemsAdapter(ml_client),
            ),
        )
        request.app.state.reply_assistant_service = service
    return service
