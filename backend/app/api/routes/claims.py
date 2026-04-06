from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_claims_service, resolve_account
from app.schemas.claims import (
    ClaimAction,
    ClaimDetail,
    ClaimListResponse,
    ClaimMessage,
    ClaimMessagePayload,
    ClaimMessageResult,
)
from app.services.claims import ClaimsService


router = APIRouter(prefix="/claims", tags=["claims"])


@router.get("", response_model=ClaimListResponse)
async def list_claims(
    service: Annotated[ClaimsService, Depends(get_claims_service)],
    account_key: Annotated[str, Depends(resolve_account)],
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    stage: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> ClaimListResponse:
    return await service.list_claims(account_key, limit=limit, offset=offset, stage=stage, status=status)


@router.get("/{claim_id}", response_model=ClaimDetail)
async def get_claim(
    claim_id: int,
    service: Annotated[ClaimsService, Depends(get_claims_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> ClaimDetail:
    return await service.get_claim(account_key, claim_id)


@router.get("/{claim_id}/messages", response_model=list[ClaimMessage])
async def get_claim_messages(
    claim_id: int,
    service: Annotated[ClaimsService, Depends(get_claims_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> list[ClaimMessage]:
    return await service.get_messages(account_key, claim_id)


@router.post("/{claim_id}/message", response_model=ClaimMessageResult)
async def post_claim_message(
    claim_id: int,
    payload: ClaimMessagePayload,
    service: Annotated[ClaimsService, Depends(get_claims_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> ClaimMessageResult:
    return await service.post_message(
        account_key,
        claim_id,
        message=payload.message,
        receiver_role=payload.receiver_role,
    )


@router.get("/{claim_id}/available-actions", response_model=list[ClaimAction])
async def get_claim_available_actions(
    claim_id: int,
    service: Annotated[ClaimsService, Depends(get_claims_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> list[ClaimAction]:
    return await service.get_available_actions(account_key, claim_id)
