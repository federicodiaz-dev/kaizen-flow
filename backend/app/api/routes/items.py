from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_items_service, resolve_account
from app.schemas.items import ItemDetail, ItemListResponse, ItemUpdatePayload
from app.services.items import ItemsService


router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=ItemListResponse)
async def list_items(
    service: Annotated[ItemsService, Depends(get_items_service)],
    account_key: Annotated[str, Depends(resolve_account)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
) -> ItemListResponse:
    return await service.list_items(account_key, limit=limit, offset=offset, status=status)


@router.get("/{item_id}", response_model=ItemDetail)
async def get_item(
    item_id: str,
    service: Annotated[ItemsService, Depends(get_items_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> ItemDetail:
    return await service.get_item(account_key, item_id)


@router.patch("/{item_id}", response_model=ItemDetail)
async def update_item(
    item_id: str,
    payload: ItemUpdatePayload,
    service: Annotated[ItemsService, Depends(get_items_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> ItemDetail:
    return await service.update_item(account_key, item_id, payload)


@router.get("/{item_id}/permalink")
async def get_item_permalink(
    item_id: str,
    service: Annotated[ItemsService, Depends(get_items_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> dict[str, str | None]:
    item = await service.get_item(account_key, item_id)
    return {"item_id": item_id, "permalink": item.permalink}
