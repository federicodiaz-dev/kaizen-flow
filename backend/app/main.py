from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.api.routes.auth import build_mercadolibre_callback_redirect
from app.core.database import Database
from app.core.exceptions import AppError
from app.core.security import generate_csrf_token
from app.core.settings import get_settings
from app.services.auth import AuthService


logger = logging.getLogger("kaizen-flow")
LANDING_INDEX = Path(__file__).resolve().parents[2] / "landing" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.database = Database(settings.database_url)
    app.state.database.initialize()
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    app.state.auth_service = AuthService(
        database=app.state.database,
        settings=settings,
        http_client=app.state.http_client,
    )
    app.state.agents_services = {}
    app.state.listing_doctor_services = {}
    try:
        yield
    finally:
        for service in app.state.agents_services.values():
            await service.aclose()
        for service in app.state.listing_doctor_services.values():
            await service.aclose()
        await app.state.http_client.aclose()


app = FastAPI(title="Kaizen Flow API", version="0.2.0", lifespan=lifespan)

settings = get_settings()
if settings.trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "X-Kaizen-Account"],
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.middleware("http")
async def apply_http_security(request: Request, call_next):
    response = await call_next(request)
    current_settings = getattr(request.app.state, "settings", settings)

    if not request.cookies.get(current_settings.csrf_cookie_name):
        response.set_cookie(
            key=current_settings.csrf_cookie_name,
            value=generate_csrf_token(),
            httponly=False,
            samesite=current_settings.csrf_cookie_same_site,
            secure=current_settings.csrf_cookie_secure,
            path="/",
            domain=current_settings.csrf_cookie_domain,
        )

    if current_settings.security_headers_enabled:
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        response.headers.setdefault("Content-Security-Policy", _build_content_security_policy())
        if current_settings.session_cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload")

    return response


def _build_content_security_policy() -> str:
    directives = [
        "default-src 'self'",
        "img-src 'self' data: https:",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
        "font-src 'self' https://fonts.gstatic.com data:",
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net",
        "connect-src 'self' https://api.mercadolibre.com https://auth.mercadolibre.com.ar",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
    return "; ".join(directives)


@app.get("/", include_in_schema=False)
async def serve_landing() -> FileResponse | RedirectResponse:
    if settings.serve_landing_from_backend and LANDING_INDEX.exists():
        return FileResponse(LANDING_INDEX)
    return RedirectResponse(url="/docs", status_code=307)


@app.get("/landing", include_in_schema=False)
async def serve_landing_alias() -> FileResponse | RedirectResponse:
    return await serve_landing()


@app.get("/auth/callback", include_in_schema=False)
async def legacy_mercadolibre_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    auth_service = getattr(request.app.state, "auth_service")
    return await build_mercadolibre_callback_redirect(
        service=auth_service,
        code=code,
        state=state,
        error=error,
        error_description=error_description,
    )


@app.exception_handler(AppError)
async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unexpected error", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "Unexpected server error.",
        },
    )
