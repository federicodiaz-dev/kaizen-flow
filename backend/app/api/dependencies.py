from __future__ import annotations

from dataclasses import replace
from typing import Annotated

import httpx
from fastapi import Depends, Header, Query, Request

from app.agents.config import get_agent_settings
from app.agents.service import BusinessAssistantService
from app.adapters.claims import ClaimsAdapter
from app.adapters.items import ItemsAdapter
from app.adapters.market_research import MarketResearchAdapter
from app.adapters.post_sale_messages import PostSaleMessagesAdapter
from app.adapters.questions import QuestionsAdapter
from app.clients.mercadolibre import MercadoLibreClient
from app.core.account_store import AccountStore
from app.core.database import Database
from app.core.exceptions import AuthenticationError, CSRFError, SubscriptionInactiveError
from app.core.rate_limit import rate_limiter
from app.core.security import safe_compare
from app.core.settings import Settings, get_settings as load_core_settings
from app.services.billing import BillingService
from app.services.accounts import AccountsService
from app.services.auth import AuthService, AuthenticatedUser
from app.services.claims import ClaimsService
from app.services.copywriter import CopywriterService
from app.services.items import ItemsService
from app.services.listing_doctor import ListingDoctorService
from app.services.market_insights import MarketInsightsService
from app.services.post_sale_messages import PostSaleMessagesService
from app.services.public_catalog import PublicCatalogService
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
        database = Database(settings.database_url)
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
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
) -> AccountStore:
    return AccountStore(
        database=database,
        user_id=current_user.id,
        workspace_id=current_user.workspace_id,
        default_account=current_user.default_account,
        encryption_key=settings.encryption_key,
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


def get_public_catalog_service(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
) -> PublicCatalogService:
    return PublicCatalogService(database=database, settings=settings)


def get_billing_service(
    database: Annotated[Database, Depends(get_database)],
) -> BillingService:
    return BillingService(database=database)


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


def get_market_insights_service(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    client: Annotated[MercadoLibreClient, Depends(get_ml_client)],
) -> MarketInsightsService:
    agent_settings = get_agent_settings()
    return MarketInsightsService(
        user_id=current_user.id,
        market_research=MarketResearchAdapter(client),
        default_site_id=agent_settings.default_site_id,
        agent_settings=agent_settings,
    )


def get_post_sale_messages_service(
    account_store: Annotated[AccountStore, Depends(get_account_store)],
    client: Annotated[MercadoLibreClient, Depends(get_ml_client)],
) -> PostSaleMessagesService:
    return PostSaleMessagesService(
        account_store=account_store,
        client=client,
        adapter=PostSaleMessagesAdapter(client),
    )


def resolve_account(
    account_store: Annotated[AccountStore, Depends(get_account_store)],
    account: str | None = Query(default=None),
    x_kaizen_account: str | None = Header(default=None, alias="X-Kaizen-Account"),
) -> str:
    return account_store.resolve_active_account_key(account or x_kaizen_account)


def get_client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else None


def require_csrf(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> None:
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    if not safe_compare(cookie_token, x_csrf_token):
        raise CSRFError()


def require_active_subscription(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    if not current_user.has_active_subscription:
        raise SubscriptionInactiveError(
            details={
                "workspace_id": current_user.workspace_id,
                "subscription_status": current_user.subscription_status,
                "plan_code": current_user.subscription_plan_code,
            },
        )
    return current_user


def enforce_auth_rate_limit(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    rate_limiter.enforce(
        bucket="auth",
        key=f"{get_client_ip(request) or 'anonymous'}:{request.url.path}",
        limit=settings.auth_rate_limit_requests,
        window_seconds=settings.auth_rate_limit_window_seconds,
    )


def enforce_checkout_rate_limit(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    rate_limiter.enforce(
        bucket="checkout",
        key=f"{get_client_ip(request) or 'anonymous'}:{request.url.path}",
        limit=settings.checkout_rate_limit_requests,
        window_seconds=settings.checkout_rate_limit_window_seconds,
    )


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
        post_sale_messages_service=PostSaleMessagesService(
            account_store=account_store,
            client=ml_client,
            adapter=PostSaleMessagesAdapter(ml_client),
        ),
        items_service=ItemsService(
            account_store=account_store,
            client=ml_client,
            items_adapter=ItemsAdapter(ml_client),
        ),
    )


def get_listing_doctor_service(
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    account_store: Annotated[AccountStore, Depends(get_account_store)],
    http_client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
    copywriter_service: Annotated[CopywriterService, Depends(get_copywriter_service)],
) -> ListingDoctorService:
    services_cache = getattr(request.app.state, "listing_doctor_services", None)
    if services_cache is None:
        services_cache = {}
        request.app.state.listing_doctor_services = services_cache

    service = services_cache.get(current_user.id)
    if service is None:
        client = MercadoLibreClient(http_client=http_client, settings=settings, account_store=account_store)
        service = ListingDoctorService(
            user_id=current_user.id,
            account_store=account_store,
            items_service=ItemsService(
                account_store=account_store,
                client=client,
                items_adapter=ItemsAdapter(client),
            ),
            market_research=MarketResearchAdapter(client),
            copywriter_service=copywriter_service,
        )
        services_cache[current_user.id] = service
    return service
