from __future__ import annotations

from typing import Any

from app.clients.mercadolibre import MercadoLibreClient


class ClaimsAdapter:
    def __init__(self, client: MercadoLibreClient) -> None:
        self._client = client

    async def list_claims(
        self,
        account_key: str,
        *,
        limit: int,
        offset: int,
        player_user_id: int,
        player_role: str,
        stage: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "player_user_id": player_user_id,
            "player_role": player_role,
            "sort": "last_updated:desc",
        }
        if stage:
            params["stage"] = stage
        if status:
            params["status"] = status
        data = await self._client.request(account_key, "GET", "/post-purchase/v1/claims/search", params=params)
        return data if isinstance(data, dict) else {}

    async def get_claim(self, account_key: str, claim_id: int) -> dict[str, Any]:
        data = await self._client.request(account_key, "GET", f"/post-purchase/v1/claims/{claim_id}")
        return data if isinstance(data, dict) else {}

    async def get_messages(self, account_key: str, claim_id: int) -> list[dict[str, Any]]:
        data = await self._client.request(account_key, "GET", f"/post-purchase/v1/claims/{claim_id}/messages")
        return data if isinstance(data, list) else []

    async def post_message(
        self,
        account_key: str,
        claim_id: int,
        *,
        receiver_role: str,
        message: str,
    ) -> Any:
        payload = {
            "receiver_role": receiver_role,
            "message": message,
            "attachments": [],
        }
        return await self._client.request(
            account_key,
            "POST",
            f"/post-purchase/v1/claims/{claim_id}/actions/send-message",
            json_body=payload,
            headers={"Content-Type": "application/json"},
        )

    async def get_status_history(self, account_key: str, claim_id: int) -> list[dict[str, Any]]:
        data = await self._client.request(account_key, "GET", f"/post-purchase/v1/claims/{claim_id}/status_history")
        return data if isinstance(data, list) else []

    async def get_expected_resolutions(self, account_key: str, claim_id: int) -> list[dict[str, Any]]:
        data = await self._client.request(
            account_key,
            "GET",
            f"/post-purchase/v1/claims/{claim_id}/expected_resolutions",
        )
        return data if isinstance(data, list) else []

    async def get_affects_reputation(self, account_key: str, claim_id: int) -> dict[str, Any]:
        data = await self._client.request(
            account_key,
            "GET",
            f"/post-purchase/v1/claims/{claim_id}/affects-reputation",
        )
        return data if isinstance(data, dict) else {}

    async def get_reason_detail(self, account_key: str, reason_id: str) -> dict[str, Any]:
        data = await self._client.request(
            account_key,
            "GET",
            f"/post-purchase/v1/reasons/{reason_id}/children",
        )
        return data if isinstance(data, dict) else {}
