from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    accounts,
    agents,
    auth,
    claims,
    copywriter,
    health,
    items,
    listing_doctor,
    market_insights,
    plans,
    post_sale_messages,
    questions,
    reply_assistant,
)


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(plans.router)
api_router.include_router(accounts.router)
api_router.include_router(agents.router)
api_router.include_router(copywriter.router)
api_router.include_router(reply_assistant.router)
api_router.include_router(listing_doctor.router)
api_router.include_router(market_insights.router)
api_router.include_router(questions.router)
api_router.include_router(claims.router)
api_router.include_router(post_sale_messages.router)
api_router.include_router(items.router)
