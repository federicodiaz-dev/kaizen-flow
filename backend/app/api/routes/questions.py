from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_questions_service, resolve_account
from app.schemas.questions import QuestionAnswerPayload, QuestionDetail, QuestionListResponse
from app.services.questions import QuestionsService


router = APIRouter(prefix="/questions", tags=["questions"])


@router.get("", response_model=QuestionListResponse)
async def list_questions(
    service: Annotated[QuestionsService, Depends(get_questions_service)],
    account_key: Annotated[str, Depends(resolve_account)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> QuestionListResponse:
    return await service.list_questions(account_key, limit=limit, offset=offset)


@router.get("/{question_id}", response_model=QuestionDetail)
async def get_question(
    question_id: int,
    service: Annotated[QuestionsService, Depends(get_questions_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> QuestionDetail:
    return await service.get_question(account_key, question_id)


@router.post("/{question_id}/answer", response_model=QuestionDetail)
async def answer_question(
    question_id: int,
    payload: QuestionAnswerPayload,
    service: Annotated[QuestionsService, Depends(get_questions_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> QuestionDetail:
    return await service.answer_question(account_key, question_id, payload.text)
