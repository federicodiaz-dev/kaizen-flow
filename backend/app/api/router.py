from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import accounts, agents, claims, copywriter, health, items, questions, reply_assistant


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(accounts.router)
api_router.include_router(agents.router)
api_router.include_router(copywriter.router)
api_router.include_router(reply_assistant.router)
api_router.include_router(questions.router)
api_router.include_router(claims.router)
api_router.include_router(items.router)
