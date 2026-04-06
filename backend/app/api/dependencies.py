from __future__ import annotations

from dataclasses import replace
from typing import Annotated

import httpx
from fastapi import Depends, Header, Query, Request

from app.agents.config import get_agent_settings
from app.agents.service import BusinessAssistantService
from app.adapters.claims import ClaimsAdapter
from app.adapters.items import ItemsAdapter
from app.adapters.questions import QuestionsAdapter
from app.clients.mercadolibre import MercadoLibreClient
from app.core.account_store import AccountStore
from app.core.database import Database
from app.core.exceptions import AuthenticationError
from app.core.settings import Settings, get_settings as load_core_settings
from app.schemas.auth import UserProfile
from app.services.accounts import AccountsService
from app.services.auth import AuthService, AuthenticatedUser
from app.services.claims import ClaimsService
from app.services.items import ItemsService
from app.services.questions import QuestionsService


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        settings = load_core_settings()
        request.app.state.settings = settings
    return settings


def get_database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:
        settings = get_settings(request)
        database = Database(settings.database_path)
        database.initialize()
        request.app.state.database = database
    return database


def get_http_client(request: Request) -> httpx.AsyncClient:
    http_client = getattr(request.app.state, "http_client", None)
    if http_client is None:
        http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        request.app.state.http_client = http_client
    return http_client


def get_auth_service(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> AuthService:
    service = getattr(request.app.state, "auth_service", None)
    if service is None:
        service = AuthService(
            database=database,
            settings=settings,
            http_client=http_client,
        )
        request.app.state.auth_service = service
    return service


def get_current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedUser:
    session_token = request.cookies.get(settings.session_cookie_name)
    if not session_token:
        raise AuthenticationError()
    return auth_service.get_user_by_session(session_token)


def get_account_store(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database, Depends(get_database)],
) -> AccountStore:
    return AccountStore(
        database=database,
        user_id=current_user.id,
        default_account=current_user.default_account,
    )


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
    return account_store.resolve_active_account_key(account or x_kaizen_account)


def get_agents_service(
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    account_store: Annotated[AccountStore, Depends(get_account_store)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> BusinessAssistantService:
    services_cache = getattr(request.app.state, "agents_services", None)
    if services_cache is None:
        services_cache = {}
        request.app.state.agents_services = services_cache

    service = services_cache.get(current_user.id)
    if service is None:
        base_agent_settings = get_agent_settings()
        scoped_agent_settings = replace(
            base_agent_settings,
            memory_dir=base_agent_settings.memory_dir / f"user_{current_user.id}",
        )
        service = BusinessAssistantService(
            settings=settings,
            account_store=account_store,
            http_client=http_client,
            agent_settings=scoped_agent_settings,
        )
        services_cache[current_user.id] = service
    return service


def get_copywriter_service(
    request: Request,
    _: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> "CopywriterService":
    from app.services.copywriter import CopywriterService as _CopywriterService

    service = getattr(request.app.state, "copywriter_service", None)
    if service is None:
        service = _CopywriterService()
        request.app.state.copywriter_service = service
    return service


def get_reply_assistant_service(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    account_store: Annotated[AccountStore, Depends(get_account_store)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> "ReplyAssistantService":
    from app.services.reply_assistant import ReplyAssistantService as _ReplyAssistantService

    ml_client = MercadoLibreClient(http_client=http_client, settings=settings, account_store=account_store)

    return _ReplyAssistantService(
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
