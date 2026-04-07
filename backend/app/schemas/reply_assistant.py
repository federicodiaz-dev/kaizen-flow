from __future__ import annotations

from pydantic import BaseModel, Field


class QuestionDraftRequest(BaseModel):
    current_draft: str | None = Field(default=None, max_length=2000)


class QuestionDraftResponse(BaseModel):
    draft_answer: str


class ClaimDraftRequest(BaseModel):
    receiver_role: str | None = Field(default=None, max_length=100)
    current_draft: str | None = Field(default=None, max_length=3500)


class ClaimDraftResponse(BaseModel):
    draft_message: str


class PostSaleDraftRequest(BaseModel):
    current_draft: str | None = Field(default=None, max_length=3500)


class PostSaleDraftResponse(BaseModel):
    draft_message: str
