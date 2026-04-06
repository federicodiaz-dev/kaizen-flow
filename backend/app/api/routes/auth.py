from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.api.dependencies import get_auth_service, get_current_user, get_settings
from app.schemas.auth import LoginRequest, RegisterRequest, SessionResponse
from app.services.auth import AuthService, AuthenticatedUser


router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(
    response: Response,
    *,
    session_token: str,
    cookie_name: str,
    secure: bool,
    max_age_seconds: int,
) -> None:
    response.set_cookie(
        key=cookie_name,
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=max_age_seconds,
        path="/",
    )


def _clear_session_cookie(response: Response, *, cookie_name: str, secure: bool) -> None:
    response.delete_cookie(
        key=cookie_name,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


@router.post("/register", response_model=SessionResponse)
def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings=Depends(get_settings),
) -> SessionResponse:
    user, session_token = service.register_user(
        email=payload.email,
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    _set_session_cookie(
        response,
        session_token=session_token,
        cookie_name=settings.session_cookie_name,
        secure=settings.session_cookie_secure,
        max_age_seconds=settings.session_ttl_hours * 60 * 60,
    )
    return SessionResponse(user=user.to_profile())


@router.post("/login", response_model=SessionResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings=Depends(get_settings),
) -> SessionResponse:
    user, session_token = service.login_user(
        email=payload.email,
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    _set_session_cookie(
        response,
        session_token=session_token,
        cookie_name=settings.session_cookie_name,
        secure=settings.session_cookie_secure,
        max_age_seconds=settings.session_ttl_hours * 60 * 60,
    )
    return SessionResponse(user=user.to_profile())


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings=Depends(get_settings),
) -> Response:
    service.logout(request.cookies.get(settings.session_cookie_name))
    _clear_session_cookie(
        response,
        cookie_name=settings.session_cookie_name,
        secure=settings.session_cookie_secure,
    )
    return response


@router.get("/me", response_model=SessionResponse)
def get_me(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> SessionResponse:
    return SessionResponse(user=current_user.to_profile())


@router.post("/onboarding/complete", response_model=SessionResponse)
def complete_onboarding(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> SessionResponse:
    user = service.complete_onboarding(current_user.id)
    return SessionResponse(user=user.to_profile())


@router.get("/mercadolibre/connect")
def begin_mercadolibre_connect(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    account_key: str | None = Query(default=None),
    label: str | None = Query(default=None),
) -> RedirectResponse:
    authorization_url = service.build_mercadolibre_authorization_url(
        user_id=current_user.id,
        requested_account_key=account_key,
        requested_label=label,
    )
    return RedirectResponse(url=authorization_url, status_code=307)


@router.get("/mercadolibre/callback", include_in_schema=False)
async def mercadolibre_callback(
    service: Annotated[AuthService, Depends(get_auth_service)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> RedirectResponse:
    return await build_mercadolibre_callback_redirect(
        service=service,
        code=code,
        state=state,
        error=error,
        error_description=error_description,
    )


async def build_mercadolibre_callback_redirect(
    *,
    service: AuthService,
    code: str | None,
    state: str | None,
    error: str | None,
    error_description: str | None,
) -> RedirectResponse:
    try:
        result = await service.complete_mercadolibre_oauth(
            code=code,
            state=state,
            error=error,
            error_description=error_description,
        )
        target = service.build_frontend_callback_url(
            success=True,
            account_key=str(result["account_key"]),
        )
    except Exception as exc:
        message = getattr(exc, "message", None) or str(exc) or "No se pudo conectar la cuenta de Mercado Libre."
        target = service.build_frontend_callback_url(success=False, message=message)
    return RedirectResponse(url=target, status_code=303)
