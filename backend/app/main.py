from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.api.routes.auth import build_mercadolibre_callback_redirect
from app.core.database import Database
from app.core.exceptions import AppError
from app.core.settings import get_settings
from app.services.auth import AuthService


logger = logging.getLogger("kaizen-flow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.database = Database(settings.database_path)
    app.state.database.initialize()
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    app.state.auth_service = AuthService(
        database=app.state.database,
        settings=settings,
        http_client=app.state.http_client,
    )
    app.state.agents_services = {}
    try:
        yield
    finally:
        for service in app.state.agents_services.values():
            await service.aclose()
        await app.state.http_client.aclose()


app = FastAPI(title="Kaizen Flow API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin, "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=get_settings().api_prefix)


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
