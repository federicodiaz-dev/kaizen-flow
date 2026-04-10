from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.routes import (
    accounts,
    agents,
    auth,
    billing,
    claims,
    copywriter,
    health,
    items,
    listing_doctor,
    market_insights,
    post_sale_messages,
    public,
    questions,
    reply_assistant,
)
from app.api.dependencies import require_active_subscription


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(public.router)
api_router.include_router(auth.router)
api_router.include_router(billing.router)
api_router.include_router(accounts.router)
api_router.include_router(agents.router, dependencies=[Depends(require_active_subscription)])
api_router.include_router(copywriter.router, dependencies=[Depends(require_active_subscription)])
api_router.include_router(reply_assistant.router, dependencies=[Depends(require_active_subscription)])
api_router.include_router(listing_doctor.router, dependencies=[Depends(require_active_subscription)])
api_router.include_router(market_insights.router, dependencies=[Depends(require_active_subscription)])
api_router.include_router(questions.router, dependencies=[Depends(require_active_subscription)])
api_router.include_router(claims.router, dependencies=[Depends(require_active_subscription)])
api_router.include_router(post_sale_messages.router, dependencies=[Depends(require_active_subscription)])
api_router.include_router(items.router, dependencies=[Depends(require_active_subscription)])
