from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ClaimAction(BaseModel):
    action: str
    due_date: str | None = None
    mandatory: bool | None = None
    player_role: str | None = None
    player_type: str | None = None
    user_id: int | None = None


class ClaimPlayer(BaseModel):
    role: str
    type: str | None = None
    user_id: int | None = None
    available_actions: list[ClaimAction] = []


class ClaimSummary(BaseModel):
    id: int
    type: str | None = None
    stage: str | None = None
    status: str | None = None
    reason_id: str | None = None
    resource: str | None = None
    resource_id: int | None = None
    parent_id: int | None = None
    date_created: str | None = None
    last_updated: str | None = None
    players: list[ClaimPlayer] = []
    available_actions: list[ClaimAction] = []


class ClaimMessageAttachment(BaseModel):
    filename: str | None = None
    original_filename: str | None = None
    size: int | None = None
    type: str | None = None
    date_created: str | None = None


class ClaimMessage(BaseModel):
    sender_role: str | None = None
    receiver_role: str | None = None
    stage: str | None = None
    date_created: str | None = None
    message: str | None = None
    attachments: list[ClaimMessageAttachment] = []


class ClaimStatusHistoryEntry(BaseModel):
    stage: str | None = None
    status: str | None = None
    date: str | None = None
    change_by: str | None = None


class ClaimExpectedResolution(BaseModel):
    player_role: str | None = None
    user_id: int | None = None
    expected_resolution: str | None = None
    status: str | None = None
    date_created: str | None = None
    last_updated: str | None = None


class ClaimReputationImpact(BaseModel):
    affects_reputation: str | None = None
    has_incentive: bool | None = None
    due_date: str | None = None


class ClaimReasonDetail(BaseModel):
    id: str | None = None
    name: str | None = None
    detail: str | None = None
    flow: str | None = None
    parent_id: str | None = None
    status: str | None = None


class ClaimDetail(ClaimSummary):
    resolution: dict | None = None
    labels: list[dict] = []
    coverages: list[dict] = []
    site_id: str | None = None
    messages: list[ClaimMessage] = []
    status_history: list[ClaimStatusHistoryEntry] = []
    expected_resolutions: list[ClaimExpectedResolution] = []
    reputation_impact: ClaimReputationImpact | None = None
    reason_detail: ClaimReasonDetail | None = None
    can_message: bool = False
    message_limitations: str | None = None
    allowed_receiver_roles: list[str] = []


class ClaimListResponse(BaseModel):
    items: list[ClaimSummary]
    total: int
    offset: int
    limit: int


class ClaimMessagePayload(BaseModel):
    receiver_role: str | None = None
    message: str = Field(min_length=1, max_length=3500)


class ClaimMessageResult(BaseModel):
    execution_response: dict[str, Any] | None = None
    new_state: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None
