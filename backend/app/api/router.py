from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import accounts, agents, claims, health, items, questions


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(accounts.router)
api_router.include_router(agents.router)
api_router.include_router(questions.router)
api_router.include_router(claims.router)
api_router.include_router(items.router)
