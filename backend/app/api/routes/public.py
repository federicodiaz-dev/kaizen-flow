from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_public_catalog_service
from app.schemas.public import PublicPlansResponse
from app.services.public_catalog import PublicCatalogService


router = APIRouter(prefix="/public", tags=["public"])


@router.get("/plans", response_model=PublicPlansResponse)
def list_public_plans(
    service: Annotated[PublicCatalogService, Depends(get_public_catalog_service)],
) -> PublicPlansResponse:
    return service.list_public_plans()
