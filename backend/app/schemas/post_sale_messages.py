from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PostSaleConversationParty(BaseModel):
    user_id: int | None = None
    name: str | None = None
    nickname: str | None = None


class PostSaleMessageAttachment(BaseModel):
    filename: str | None = None
    original_filename: str | None = None
    size: int | None = None
    type: str | None = None
    date_created: str | None = None
    potential_security_threat: bool | None = None


class PostSaleMessage(BaseModel):
    id: str | None = None
    site_id: str | None = None
    client_id: str | None = None
    text: str | None = None
    status: str | None = None
    date_created: str | None = None
    date_received: str | None = None
    date_available: str | None = None
    date_notified: str | None = None
    date_read: str | None = None
    from_user: PostSaleConversationParty | None = None
    to_users: list[PostSaleConversationParty] = Field(default_factory=list)
    attachments: list[PostSaleMessageAttachment] = Field(default_factory=list)
    moderation_status: str | None = None
    moderation_substatus: str | None = None
    moderation_source: str | None = None
    moderation_date: str | None = None
    conversation_first_message: bool | None = None
    is_from_seller: bool = False


class PostSaleOrderItemRef(BaseModel):
    item_id: str | None = None
    title: str | None = None
    quantity: int | None = None
    unit_price: float | None = None
    currency_id: str | None = None
    full_unit_price: float | None = None
    variation_id: int | None = None
    thumbnail: str | None = None


class PostSaleOrderRef(BaseModel):
    id: int
    pack_id: str | None = None
    status: str | None = None
    status_detail: str | None = None
    date_created: str | None = None
    date_closed: str | None = None
    last_updated: str | None = None
    total_amount: float | None = None
    paid_amount: float | None = None
    currency_id: str | None = None
    shipping_id: int | None = None
    tags: list[str] = Field(default_factory=list)
    items: list[PostSaleOrderItemRef] = Field(default_factory=list)


class PostSaleConversationSummary(BaseModel):
    pack_id: str
    buyer_user_id: int | None = None
    buyer_name: str | None = None
    buyer_nickname: str | None = None
    primary_item_title: str | None = None
    item_titles: list[str] = Field(default_factory=list)
    order_ids: list[int] = Field(default_factory=list)
    date_created: str | None = None
    last_updated: str | None = None
    unread_count: int = 0
    message_count: int = 0
    conversation_status: str | None = None
    conversation_substatus: str | None = None
    pack_status: str | None = None
    pack_status_detail: str | None = None
    seller_max_message_length: int | None = None
    buyer_max_message_length: int | None = None
    can_reply: bool = False
    reply_limitations: str | None = None
    site_id: str | None = None
    shipping_id: int | None = None
    total_amount: float | None = None
    currency_id: str | None = None
    claim_ids: list[int] = Field(default_factory=list)


class PostSaleConversationDetail(PostSaleConversationSummary):
    seller_user_id: int | None = None
    messages: list[PostSaleMessage] = Field(default_factory=list)
    orders: list[PostSaleOrderRef] = Field(default_factory=list)


class PostSaleConversationListResponse(BaseModel):
    items: list[PostSaleConversationSummary]
    total: int
    offset: int
    limit: int


class PostSaleReplyPayload(BaseModel):
    text: str = Field(min_length=1, max_length=3500)


class PostSaleMessageResult(BaseModel):
    raw: dict[str, Any] | None = None
