from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(slots=True)
class AppError(Exception):
    message: str
    status_code: int = 500
    code: str = "app_error"
    details: Any | None = None


class ConfigurationError(AppError):
    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(message=message, status_code=500, code="configuration_error", details=details)


class NotFoundError(AppError):
    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(message=message, status_code=404, code="not_found", details=details)


class BadRequestError(AppError):
    def __init__(self, message: str, details: Any | None = None) -> None:
        super().__init__(message=message, status_code=400, code="bad_request", details=details)


class MercadoLibreAPIError(AppError):
    @classmethod
    def from_response(cls, response: httpx.Response) -> "MercadoLibreAPIError":
        payload: Any | None
        try:
            payload = response.json()
        except ValueError:
            payload = None

        message = response.text.strip() or response.reason_phrase or "Mercado Libre API request failed."
        code = "mercadolibre_api_error"

        if isinstance(payload, dict):
            message = (
                str(payload.get("message"))
                or str(payload.get("error_description"))
                or str(payload.get("error"))
                or message
            )
            code = str(payload.get("error") or payload.get("code") or code)

        return cls(message=message, status_code=response.status_code, code=code, details=payload)
