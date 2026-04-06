from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_reply_assistant_service, resolve_account
from app.schemas.reply_assistant import (
    ClaimDraftRequest,
    ClaimDraftResponse,
    QuestionDraftRequest,
    QuestionDraftResponse,
)
from app.services.reply_assistant import ReplyAssistantService


router = APIRouter(prefix="/reply-assistant", tags=["reply-assistant"])


@router.post("/questions/{question_id}/draft", response_model=QuestionDraftResponse)
async def suggest_question_answer(
    question_id: int,
    payload: QuestionDraftRequest,
    service: Annotated[ReplyAssistantService, Depends(get_reply_assistant_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> QuestionDraftResponse:
    return await service.suggest_question_answer(account_key, question_id, payload)


@router.post("/claims/{claim_id}/draft", response_model=ClaimDraftResponse)
async def suggest_claim_message(
    claim_id: int,
    payload: ClaimDraftRequest,
    service: Annotated[ReplyAssistantService, Depends(get_reply_assistant_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> ClaimDraftResponse:
    return await service.suggest_claim_message(account_key, claim_id, payload)
