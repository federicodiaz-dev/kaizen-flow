from __future__ import annotations

from app.adapters.items import ItemsAdapter
from app.clients.mercadolibre import MercadoLibreClient
from app.core.account_store import AccountStore
from app.core.exceptions import BadRequestError
from app.schemas.items import ItemDetail, ItemListResponse, ItemSummary, ItemUpdatePayload


def _serialize_item(raw: dict) -> ItemSummary:
    return ItemSummary(
        id=str(raw["id"]),
        title=str(raw.get("title") or ""),
        price=raw.get("price"),
        currency_id=raw.get("currency_id"),
        available_quantity=raw.get("available_quantity"),
        sold_quantity=raw.get("sold_quantity"),
        status=raw.get("status"),
        permalink=raw.get("permalink"),
        thumbnail=raw.get("thumbnail"),
        last_updated=raw.get("last_updated"),
    )


class ItemsService:
    def __init__(
        self,
        account_store: AccountStore,
        client: MercadoLibreClient,
        items_adapter: ItemsAdapter,
    ) -> None:
        self._account_store = account_store
        self._client = client
        self._items_adapter = items_adapter

    async def _resolve_user_id(self, account_key: str) -> int:
        account = self._account_store.get_account(account_key)
        if account.user_id:
            return account.user_id

        me = await self._client.get_me(account_key)
        user_id = int(me["id"])
        self._account_store.update_account_tokens(
            account_key,
            access_token=account.access_token,
            refresh_token=account.refresh_token,
            scope=account.scope,
            user_id=user_id,
        )
        return user_id

    async def list_items(
        self,
        account_key: str,
        *,
        limit: int,
        offset: int,
        status: str | None,
    ) -> ItemListResponse:
        user_id = await self._resolve_user_id(account_key)
        payload = await self._items_adapter.list_item_ids(
            account_key,
            user_id=user_id,
            limit=limit,
            offset=offset,
            status=status,
        )
        item_ids = payload.get("results") if isinstance(payload.get("results"), list) else []
        total = int(payload.get("paging", {}).get("total") or len(item_ids))
        raw_items = await self._items_adapter.get_items(account_key, [str(item_id) for item_id in item_ids])
        items = [
            _serialize_item(entry["body"])
            for entry in raw_items
            if isinstance(entry, dict) and entry.get("code") == 200 and isinstance(entry.get("body"), dict)
        ]
        return ItemListResponse(items=items, total=total, offset=offset, limit=limit)

    async def get_item(self, account_key: str, item_id: str) -> ItemDetail:
        import asyncio
        results = await asyncio.gather(
            self._items_adapter.get_item(account_key, item_id),
            self._items_adapter.get_item_description(account_key, item_id),
            return_exceptions=True
        )
        raw: dict = results[0] if isinstance(results[0], dict) else {}
        desc_data: dict = results[1] if isinstance(results[1], dict) else {}
        
        summary = _serialize_item(raw)
        return ItemDetail(
            **summary.model_dump(),
            seller_id=raw.get("seller_id"),
            category_id=raw.get("category_id"),
            listing_type_id=raw.get("listing_type_id"),
            condition=raw.get("condition"),
            health=raw.get("health"),
            variations=raw.get("variations") or [],
            attributes=raw.get("attributes") or [],
            pictures=raw.get("pictures") or [],
            description=desc_data.get("plain_text") or "",
        )

    async def update_item(self, account_key: str, item_id: str, payload: ItemUpdatePayload) -> ItemDetail:
        update_data = payload.model_dump(exclude_none=True)
        if not update_data:
            raise BadRequestError("No item fields were provided for update.")
            
        desc = update_data.pop("description", None)
        
        import asyncio
        tasks = []
        if update_data:
            tasks.append(self._items_adapter.update_item(account_key, item_id, update_data))
        if desc is not None:
            tasks.append(self._items_adapter.update_item_description(account_key, item_id, {"plain_text": desc}))
            
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    raise r
                    
        return await self.get_item(account_key, item_id)
