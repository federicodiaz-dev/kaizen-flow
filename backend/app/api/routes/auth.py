from __future__ import annotations

import json
from html import escape
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.dependencies import get_auth_service, get_current_user, get_settings
from app.schemas.auth import (
    LoginRequest,
    MercadoLibreCompleteRequest,
    MercadoLibreCompleteResponse,
    RegisterRequest,
    SessionResponse,
)
from app.services.auth import AuthService, AuthenticatedUser


router = APIRouter(prefix="/auth", tags=["auth"])


def _extract_frontend_origin(request: Request, settings) -> str | None:
    candidates: list[str] = []
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if origin:
        candidates.append(origin)
    if referer:
        parsed = urlparse(referer)
        if parsed.scheme and parsed.netloc:
            candidates.append(f"{parsed.scheme}://{parsed.netloc}")

    allowed_origins = {item.rstrip("/") for item in settings.frontend_origins}
    for candidate in candidates:
        normalized = str(candidate).strip().rstrip("/")
        if normalized in allowed_origins:
            return normalized
    return None


def _extract_client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else None


def _set_session_cookie(
    response: Response,
    *,
    session_token: str,
    cookie_name: str,
    secure: bool,
    samesite: str,
    max_age_seconds: int,
) -> None:
    response.set_cookie(
        key=cookie_name,
        value=session_token,
        httponly=True,
        samesite=samesite,
        secure=secure,
        max_age=max_age_seconds,
        path="/",
    )


def _clear_session_cookie(
    response: Response,
    *,
    cookie_name: str,
    secure: bool,
    samesite: str,
) -> None:
    response.delete_cookie(
        key=cookie_name,
        httponly=True,
        samesite=samesite,
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
        username=payload.username,
        password=payload.password,
        selected_plan_code=payload.selected_plan_code,
        user_agent=request.headers.get("user-agent"),
        ip_address=_extract_client_ip(request),
    )
    _set_session_cookie(
        response,
        session_token=session_token,
        cookie_name=settings.session_cookie_name,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
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
        identifier=(payload.login or payload.email or "").strip(),
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=_extract_client_ip(request),
    )
    _set_session_cookie(
        response,
        session_token=session_token,
        cookie_name=settings.session_cookie_name,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
        max_age_seconds=settings.session_ttl_hours * 60 * 60,
    )
    return SessionResponse(user=user.to_profile())


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    service: Annotated[AuthService, Depends(get_auth_service)],
    settings=Depends(get_settings),
) -> Response:
    response = Response(status_code=204)
    service.logout(request.cookies.get(settings.session_cookie_name))
    _clear_session_cookie(
        response,
        cookie_name=settings.session_cookie_name,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,
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
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
    account_key: str | None = Query(default=None),
    label: str | None = Query(default=None),
    settings=Depends(get_settings),
) -> RedirectResponse:
    authorization_url = service.build_mercadolibre_authorization_url(
        user_id=current_user.id,
        requested_account_key=account_key,
        requested_label=label,
        return_origin=_extract_frontend_origin(request, settings),
    )
    return RedirectResponse(url=authorization_url, status_code=307)


@router.get("/mercadolibre/callback", include_in_schema=False)
async def mercadolibre_callback(
    service: Annotated[AuthService, Depends(get_auth_service)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    ) -> HTMLResponse:
    return await build_mercadolibre_callback_redirect(
        service=service,
        code=code,
        state=state,
        error=error,
        error_description=error_description,
    )


@router.post("/mercadolibre/complete", response_model=MercadoLibreCompleteResponse)
async def mercadolibre_complete(
    payload: MercadoLibreCompleteRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> MercadoLibreCompleteResponse:
    result = await service.complete_mercadolibre_oauth(
        code=payload.code,
        state=payload.state,
        error=payload.error,
        error_description=payload.error_description,
    )
    return MercadoLibreCompleteResponse(
        account_key=str(result["account_key"]),
        account_label=str(result["account_label"]),
        ml_user_id=int(result["ml_user_id"]),
    )


async def build_mercadolibre_callback_redirect(
    *,
    service: AuthService,
    code: str | None,
    state: str | None,
    error: str | None,
    error_description: str | None,
) -> HTMLResponse:
    frontend_origin = service.get_oauth_frontend_origin(state)
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
            frontend_origin=str(result["frontend_origin"]),
        )
    except Exception as exc:
        message = getattr(exc, "message", None) or str(exc) or "No se pudo conectar la cuenta de Mercado Libre."
        target = service.build_frontend_callback_url(
            success=False,
            message=message,
            frontend_origin=frontend_origin,
        )

    escaped_target = escape(target, quote=True)
    script_target = json.dumps(target)
    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Redireccionando a Kaizen Flow</title>
  <meta http-equiv="refresh" content="0;url={escaped_target}">
</head>
<body>
  <script>
    window.location.replace({script_target});
  </script>
  <p>Redireccionando a Kaizen Flow...</p>
  <p>Si no avanza automáticamente, abrí <a href="{escaped_target}">{escaped_target}</a>.</p>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)
