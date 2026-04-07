from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_post_sale_messages_service, resolve_account
from app.schemas.post_sale_messages import (
    PostSaleConversationDetail,
    PostSaleConversationListResponse,
    PostSaleMessageResult,
    PostSaleReplyPayload,
)
from app.services.post_sale_messages import PostSaleMessagesService


router = APIRouter(prefix="/post-sale-messages", tags=["post-sale-messages"])


@router.get("", response_model=PostSaleConversationListResponse)
async def list_post_sale_conversations(
    service: Annotated[PostSaleMessagesService, Depends(get_post_sale_messages_service)],
    account_key: Annotated[str, Depends(resolve_account)],
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> PostSaleConversationListResponse:
    return await service.list_conversations(account_key, limit=limit, offset=offset)


@router.get("/{pack_id}", response_model=PostSaleConversationDetail)
async def get_post_sale_conversation(
    pack_id: str,
    service: Annotated[PostSaleMessagesService, Depends(get_post_sale_messages_service)],
    account_key: Annotated[str, Depends(resolve_account)],
    mark_as_read: bool = Query(default=False),
) -> PostSaleConversationDetail:
    return await service.get_conversation(account_key, pack_id, mark_as_read=mark_as_read)


@router.post("/{pack_id}/reply", response_model=PostSaleMessageResult)
async def reply_post_sale_conversation(
    pack_id: str,
    payload: PostSaleReplyPayload,
    service: Annotated[PostSaleMessagesService, Depends(get_post_sale_messages_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> PostSaleMessageResult:
    return await service.reply_to_conversation(account_key, pack_id, text=payload.text)
