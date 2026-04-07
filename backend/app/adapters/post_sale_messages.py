from __future__ import annotations

from typing import Any

from app.clients.mercadolibre import MercadoLibreClient


class PostSaleMessagesAdapter:
    def __init__(self, client: MercadoLibreClient) -> None:
        self._client = client

    async def list_recent_orders(
        self,
        account_key: str,
        *,
        seller_id: int,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        params = {
            "seller": seller_id,
            "sort": "date_desc",
            "limit": limit,
            "offset": offset,
        }
        data = await self._client.request(account_key, "GET", "/orders/search", params=params)
        return data if isinstance(data, dict) else {}

    async def get_pack(self, account_key: str, pack_id: str) -> dict[str, Any]:
        data = await self._client.request(account_key, "GET", f"/packs/{pack_id}")
        return data if isinstance(data, dict) else {}

    async def get_order(self, account_key: str, order_id: int) -> dict[str, Any]:
        data = await self._client.request(account_key, "GET", f"/orders/{order_id}")
        return data if isinstance(data, dict) else {}

    async def get_unread_messages(
        self,
        account_key: str,
        *,
        role: str = "seller",
    ) -> dict[str, Any]:
        data = await self._client.request(
            account_key,
            "GET",
            "/messages/unread",
            params={"role": role, "tag": "post_sale"},
        )
        return data if isinstance(data, dict) else {}

    async def get_pack_messages(
        self,
        account_key: str,
        *,
        pack_id: str,
        seller_id: int,
        mark_as_read: bool,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        data = await self._client.request(
            account_key,
            "GET",
            f"/messages/packs/{pack_id}/sellers/{seller_id}",
            params={
                "tag": "post_sale",
                "mark_as_read": str(mark_as_read).lower(),
                "limit": limit,
                "offset": offset,
            },
        )
        return data if isinstance(data, dict) else {}

    async def post_message(
        self,
        account_key: str,
        *,
        pack_id: str,
        seller_id: int,
        buyer_user_id: int,
        text: str,
    ) -> Any:
        payload = {
            "from": {"user_id": seller_id},
            "to": {"user_id": buyer_user_id},
            "text": text,
            "attachments": [],
        }
        return await self._client.request(
            account_key,
            "POST",
            f"/messages/packs/{pack_id}/sellers/{seller_id}",
            params={"tag": "post_sale"},
            json_body=payload,
            headers={"Content-Type": "application/json"},
        )
