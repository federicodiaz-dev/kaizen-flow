from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_market_insights_service, resolve_account
from app.schemas.market_insights import MarketTrendReportRequest, MarketTrendReportResponse
from app.services.market_insights import MarketInsightsService


router = APIRouter(prefix="/market-insights", tags=["market-insights"])


@router.post("/trend-report", response_model=MarketTrendReportResponse)
async def build_trend_report(
    payload: MarketTrendReportRequest,
    service: Annotated[MarketInsightsService, Depends(get_market_insights_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> MarketTrendReportResponse:
    result = await service.build_trend_report(
        account_key=account_key,
        site_id=payload.site_id,
        natural_query=payload.natural_query,
        limit=payload.limit,
    )
    return MarketTrendReportResponse.model_validate(result)
