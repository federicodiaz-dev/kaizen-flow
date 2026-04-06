from __future__ import annotations

from typing import Any

import httpx

from app.core.account_store import AccountStore
from app.core.exceptions import ConfigurationError, MercadoLibreAPIError
from app.core.settings import Settings


class MercadoLibreClient:
    def __init__(self, http_client: httpx.AsyncClient, settings: Settings, account_store: AccountStore) -> None:
        self._http_client = http_client
        self._settings = settings
        self._account_store = account_store

    async def refresh_access_token(self, account_key: str) -> None:
        account = self._account_store.get_account(account_key)
        if not account.refresh_token:
            raise ConfigurationError(
                f"The account '{account_key}' does not have a refresh token configured.",
            )

        payload = {
            "grant_type": "refresh_token",
            "client_id": self._settings.app_id,
            "client_secret": self._settings.client_secret,
            "refresh_token": account.refresh_token,
        }
        response = await self._http_client.post(
            f"{self._settings.auth_base_url.rstrip('/')}/oauth/token",
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.is_error:
            raise MercadoLibreAPIError.from_response(response)

        data = response.json()
        self._account_store.update_account_tokens(
            account_key,
            access_token=str(data["access_token"]),
            refresh_token=str(data.get("refresh_token")) if data.get("refresh_token") else None,
            scope=str(data.get("scope")) if data.get("scope") else None,
            user_id=int(data["user_id"]) if data.get("user_id") else None,
        )

    async def request(
        self,
        account_key: str,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        retry_on_unauthorized: bool = True,
    ) -> Any:
        account = self._account_store.get_account(account_key)
        request_headers = {
            "Authorization": f"Bearer {account.access_token}",
            "Accept": "application/json",
        }
        if headers:
            request_headers.update(headers)

        response = await self._http_client.request(
            method=method.upper(),
            url=f"{self._settings.api_base_url.rstrip('/')}/{path.lstrip('/')}",
            params=params,
            json=json_body,
            headers=request_headers,
        )

        if response.status_code == 401 and retry_on_unauthorized and account.refresh_token:
            await self.refresh_access_token(account_key)
            return await self.request(
                account_key,
                method,
                path,
                params=params,
                json_body=json_body,
                headers=headers,
                retry_on_unauthorized=False,
            )

        if response.is_error:
            raise MercadoLibreAPIError.from_response(response)

        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except ValueError:
            return response.text

    async def get_me(self, account_key: str) -> dict[str, Any]:
        data = await self.request(account_key, "GET", "/users/me")
        if not isinstance(data, dict):
            raise ConfigurationError("Unexpected response while resolving the authenticated Mercado Libre user.")
        return data
