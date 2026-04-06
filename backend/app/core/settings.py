from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .env_parser import parse_env_file


ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_PATH = ROOT_DIR / ".env"


def _first(values: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = values.get(key)
        if value not in (None, ""):
            return value
    return None


def _to_int(value: Any | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _slugify(text: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return normalized or "legacy"


@dataclass(slots=True)
class AccountCredentials:
    key: str
    label: str
    access_token: str
    refresh_token: str | None = None
    scope: str | None = None
    user_id: int | None = None
    source: str = "env"


@dataclass(slots=True)
class Settings:
    app_name: str
    api_prefix: str
    api_base_url: str
    auth_base_url: str
    app_id: str
    client_secret: str
    redirect_uri: str | None
    frontend_origin: str
    default_account: str
    accounts: dict[str, AccountCredentials]


def _load_prefixed_account(values: dict[str, Any], account_key: str, label: str) -> AccountCredentials | None:
    prefix = f"ML_{account_key.upper()}"
    access_token = _first(values, f"{prefix}_ACCESS_TOKEN", f"{prefix}_TOKEN")
    if not access_token:
        return None

    return AccountCredentials(
        key=account_key,
        label=label,
        access_token=str(access_token),
        refresh_token=_first(values, f"{prefix}_REFRESH_TOKEN"),
        scope=_first(values, f"{prefix}_SCOPE"),
        user_id=_to_int(_first(values, f"{prefix}_USER_ID")),
        source="env_prefixed",
    )


def _load_legacy_account(values: dict[str, Any]) -> AccountCredentials | None:
    access_token = _first(values, "ML_ACCESS_TOKEN", "ACCESS_TOKEN", "access_token")
    if not access_token:
        return None

    return AccountCredentials(
        key="seller",
        label="Seller",
        access_token=str(access_token),
        refresh_token=_first(values, "ML_REFRESH_TOKEN", "REFRESH_TOKEN", "refresh_token"),
        scope=_first(values, "ML_SCOPE", "SCOPE", "scope"),
        user_id=_to_int(_first(values, "ML_USER_ID", "USER_ID", "user_id")),
        source="env_legacy",
    )


def _load_json_accounts(json_blocks: list[dict[str, Any]], accounts: dict[str, AccountCredentials]) -> None:
    seen_tokens = {account.access_token for account in accounts.values()}
    seen_users = {account.user_id for account in accounts.values() if account.user_id is not None}

    for index, block in enumerate(json_blocks, start=1):
        access_token = block.get("access_token")
        if not access_token or access_token in seen_tokens:
            continue

        user_id = _to_int(block.get("user_id"))
        if user_id is not None and user_id in seen_users:
            continue

        suggested_name = block.get("account_type") or block.get("label") or block.get("name") or f"legacy_{index}"
        key = _slugify(str(suggested_name))
        while key in accounts:
            key = f"{key}_{index}"

        accounts[key] = AccountCredentials(
            key=key,
            label=str(block.get("label") or block.get("name") or f"Legacy {index}"),
            access_token=str(access_token),
            refresh_token=str(block["refresh_token"]) if block.get("refresh_token") else None,
            scope=str(block["scope"]) if block.get("scope") else None,
            user_id=user_id,
            source=f"env_json:{index}",
        )
        seen_tokens.add(str(access_token))
        if user_id is not None:
            seen_users.add(user_id)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_file_values, json_blocks = parse_env_file(ENV_PATH)
    merged_values: dict[str, Any] = {**env_file_values, **os.environ}

    accounts: dict[str, AccountCredentials] = {}
    for key, label in (("seller", "Seller"), ("personal", "Personal"), ("buyer", "Buyer")):
        account = _load_prefixed_account(merged_values, key, label)
        if account:
            accounts[key] = account

    legacy_account = _load_legacy_account(merged_values)
    if legacy_account and "seller" not in accounts:
        accounts["seller"] = legacy_account

    _load_json_accounts(json_blocks, accounts)

    default_account = str(
        _first(merged_values, "ML_DEFAULT_ACCOUNT")
        or ("seller" if "seller" in accounts else next(iter(accounts), "seller"))
    )

    return Settings(
        app_name="Kaizen Flow API",
        api_prefix="/api",
        api_base_url=str(_first(merged_values, "ML_API_BASE") or "https://api.mercadolibre.com"),
        auth_base_url=str(_first(merged_values, "ML_AUTH_BASE") or "https://api.mercadolibre.com"),
        app_id=str(_first(merged_values, "ML_APP_ID") or ""),
        client_secret=str(_first(merged_values, "ML_CLIENT_SECRET") or ""),
        redirect_uri=str(_first(merged_values, "ML_REDIRECT_URI")) if _first(merged_values, "ML_REDIRECT_URI") else None,
        frontend_origin=str(_first(merged_values, "FRONTEND_ORIGIN") or "http://localhost:4200"),
        default_account=default_account,
        accounts=accounts,
    )
