from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response

from app.api.dependencies import (
    enforce_checkout_rate_limit,
    get_auth_service,
    get_billing_service,
    get_current_user,
    get_settings,
    require_csrf,
)
from app.schemas.billing import CheckoutSimulationResponse, SimulatedCheckoutRequest
from app.services.auth import AuthService, AuthenticatedUser
from app.services.billing import BillingService


router = APIRouter(prefix="/billing", tags=["billing"])


@router.post(
    "/checkout/simulate",
    response_model=CheckoutSimulationResponse,
    dependencies=[Depends(require_csrf), Depends(enforce_checkout_rate_limit)],
)
def simulate_checkout(
    payload: SimulatedCheckoutRequest,
    request: Request,
    response: Response,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    billing_service: Annotated[BillingService, Depends(get_billing_service)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    settings=Depends(get_settings),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CheckoutSimulationResponse:
    billing_service.simulate_checkout(
        current_user=current_user,
        plan_code=payload.plan_code,
        idempotency_key=idempotency_key,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )

    refreshed_user = auth_service.get_user_by_id(current_user.id)
    rotated_session_token = auth_service.rotate_session(
        current_session_token=request.cookies.get(settings.session_cookie_name),
        user=refreshed_user,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    response.set_cookie(
        key=settings.session_cookie_name,
        value=rotated_session_token,
        httponly=True,
        samesite=settings.session_cookie_same_site,
        secure=settings.session_cookie_secure,
        max_age=settings.session_ttl_hours * 60 * 60,
        path="/",
        domain=settings.session_cookie_domain,
    )
    return CheckoutSimulationResponse(**refreshed_user.to_session_response(
        csrf_token=request.cookies.get(settings.csrf_cookie_name)
    ).model_dump())
