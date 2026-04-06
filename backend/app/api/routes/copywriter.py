from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_copywriter_service
from app.schemas.copywriter import (
    CopywriterGenerateRequest,
    CopywriterGenerateResponse,
    DescriptionEnhanceRequest,
    DescriptionEnhanceResponse,
)
from app.services.copywriter import CopywriterService

router = APIRouter(prefix="/copywriter", tags=["copywriter"])


@router.post("/generate", response_model=CopywriterGenerateResponse)
async def generate_listing(
    payload: CopywriterGenerateRequest,
    service: Annotated[CopywriterService, Depends(get_copywriter_service)],
) -> CopywriterGenerateResponse:
    return await service.generate_listing(payload)


@router.post("/enhance-description", response_model=DescriptionEnhanceResponse)
async def enhance_description(
    payload: DescriptionEnhanceRequest,
    service: Annotated[CopywriterService, Depends(get_copywriter_service)],
) -> DescriptionEnhanceResponse:
    return await service.enhance_description(payload)
