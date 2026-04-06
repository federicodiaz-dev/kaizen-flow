from __future__ import annotations

from pydantic import BaseModel, Field


class QuestionItemRef(BaseModel):
    id: str
    title: str | None = None
    permalink: str | None = None
    status: str | None = None


class QuestionAnswer(BaseModel):
    text: str | None = None
    status: str | None = None
    date_created: str | None = None


class QuestionSummary(BaseModel):
    id: int
    text: str
    status: str | None = None
    date_created: str | None = None
    hold: bool = False
    deleted_from_listing: bool = False
    from_user_id: int | None = None
    item: QuestionItemRef | None = None
    answer: QuestionAnswer | None = None
    has_answer: bool = False


class QuestionDetail(QuestionSummary):
    seller_id: int | None = None
    can_answer: bool = False
    answer_limitations: str | None = None


class QuestionListResponse(BaseModel):
    items: list[QuestionSummary]
    total: int
    offset: int
    limit: int


class QuestionAnswerPayload(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
