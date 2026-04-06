from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agents.service import BusinessAssistantService
from app.api.router import api_router
from app.core.account_store import AccountStore
from app.core.exceptions import AppError
from app.core.settings import get_settings


logger = logging.getLogger("kaizen-flow")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.account_store = AccountStore(settings.accounts, settings.default_account)
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
    app.state.agents_service = BusinessAssistantService(
        settings=settings,
        account_store=app.state.account_store,
        http_client=app.state.http_client,
    )
    try:
        yield
    finally:
        await app.state.agents_service.aclose()
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
