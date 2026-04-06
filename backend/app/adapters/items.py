from __future__ import annotations

from typing import Any

from app.clients.mercadolibre import MercadoLibreClient


class ItemsAdapter:
    def __init__(self, client: MercadoLibreClient) -> None:
        self._client = client

    async def list_item_ids(
        self,
        account_key: str,
        *,
        user_id: int,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        data = await self._client.request(account_key, "GET", f"/users/{user_id}/items/search", params=params)
        return data if isinstance(data, dict) else {}

    async def get_items(self, account_key: str, item_ids: list[str]) -> list[dict[str, Any]]:
        if not item_ids:
            return []

        data = await self._client.request(
            account_key,
            "GET",
            "/items",
            params={"ids": ",".join(item_ids)},
        )
        return data if isinstance(data, list) else []

    async def get_item(self, account_key: str, item_id: str) -> dict[str, Any]:
        data = await self._client.request(account_key, "GET", f"/items/{item_id}")
        return data if isinstance(data, dict) else {}

    async def update_item(self, account_key: str, item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = await self._client.request(
            account_key,
            "PUT",
            f"/items/{item_id}",
            json_body=payload,
            headers={"Content-Type": "application/json"},
        )
        return data if isinstance(data, dict) else {}
