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

    @property
    def has_caller_id(self) -> bool:
        return bool(self._settings.app_id)

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
        include_caller_id: bool = False,
    ) -> Any:
        account = self._account_store.get_account(account_key)
        request_headers = {
            "Authorization": f"Bearer {account.access_token}",
            "Accept": "application/json",
            "User-Agent": "KaizenFlow/1.0",
        }
        if include_caller_id and self._settings.app_id:
            request_headers["X-Caller-Id"] = self._settings.app_id
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
                include_caller_id=include_caller_id,
            )

        if response.is_error:
            raise MercadoLibreAPIError.from_response(response)

        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except ValueError:
            return response.text

    async def public_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        include_caller_id: bool = False,
    ) -> Any:
        request_headers = {
            "Accept": "application/json",
            "User-Agent": "KaizenFlow/1.0",
        }
        if include_caller_id and self._settings.app_id:
            request_headers["X-Caller-Id"] = self._settings.app_id
        if headers:
            request_headers.update(headers)

        response = await self._http_client.request(
            method=method.upper(),
            url=f"{self._settings.api_base_url.rstrip('/')}/{path.lstrip('/')}",
            params=params,
            json=json_body,
            headers=request_headers,
        )

        if response.is_error:
            raise MercadoLibreAPIError.from_response(response)

        if response.status_code == 204 or not response.content:
            return None

        try:
            return response.json()
        except ValueError:
            return response.text

    async def public_page_request(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> str:
        request_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.7",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
        }
        if headers:
            request_headers.update(headers)

        response = await self._http_client.get(url, headers=request_headers, follow_redirects=True)
        if response.is_error:
            raise MercadoLibreAPIError.from_response(response)
        return response.text

    async def get_me(self, account_key: str) -> dict[str, Any]:
        data = await self.request(account_key, "GET", "/users/me")
        if not isinstance(data, dict):
            raise ConfigurationError("Unexpected response while resolving the authenticated Mercado Libre user.")
        return data
