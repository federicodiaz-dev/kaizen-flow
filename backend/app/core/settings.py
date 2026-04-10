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

DEFAULT_LOCAL_ORIGINS = [
    "http://localhost:4200",
    "http://127.0.0.1:4200",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]


def _first(values: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = values.get(key)
        if value not in (None, ""):
            return value
    return None


def _to_int(value: Any | None, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _to_bool(value: Any | None, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_same_site(value: Any | None, default: str = "lax") -> str:
    normalized = str(value or default).strip().lower()
    if normalized not in {"lax", "strict", "none"}:
        return default
    return normalized


def _split_csv(value: Any | None) -> list[str]:
    if value in (None, ""):
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


def _slugify(text: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return normalized or "workspace"


@dataclass(slots=True)
class AccountCredentials:
    key: str
    label: str
    access_token: str
    refresh_token: str | None = None
    scope: str | None = None
    user_id: int | None = None
    source: str = "oauth"
    is_active: bool = True


@dataclass(slots=True)
class Settings:
    app_name: str
    api_prefix: str
    api_base_url: str
    auth_base_url: str
    oauth_authorize_url: str
    app_id: str
    client_secret: str
    redirect_uri: str | None
    frontend_origin: str
    landing_origin: str
    public_app_url: str
    cors_allowed_origins: list[str]
    trusted_hosts: list[str]
    database_url: str
    legacy_database_path: Path
    session_cookie_name: str
    session_cookie_secure: bool
    session_cookie_same_site: str
    session_cookie_domain: str | None
    session_ttl_hours: int
    csrf_cookie_name: str
    csrf_cookie_secure: bool
    csrf_cookie_same_site: str
    csrf_cookie_domain: str | None
    encryption_key: str
    password_pepper: str | None
    auth_rate_limit_requests: int
    auth_rate_limit_window_seconds: int
    checkout_rate_limit_requests: int
    checkout_rate_limit_window_seconds: int
    security_headers_enabled: bool
    serve_landing_from_backend: bool
    default_plan_code: str


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_file_values, _ = parse_env_file(ENV_PATH)
    merged_values: dict[str, Any] = {**env_file_values, **os.environ}

    frontend_origin = str(_first(merged_values, "FRONTEND_ORIGIN") or "http://localhost:4200").rstrip("/")
    landing_origin = str(_first(merged_values, "LANDING_ORIGIN") or frontend_origin).rstrip("/")
    public_app_url = str(_first(merged_values, "PUBLIC_APP_URL") or frontend_origin).rstrip("/")

    database_url = str(_first(merged_values, "APP_DATABASE_URL", "DATABASE_URL", "POSTGRES_URL") or "").strip()
    legacy_db_raw = str(_first(merged_values, "APP_DB_PATH") or "backend/data/kaizen_flow.sqlite3")
    legacy_database_path = (
        Path(legacy_db_raw).resolve() if Path(legacy_db_raw).is_absolute() else (ROOT_DIR / legacy_db_raw).resolve()
    )

    configured_origins = _split_csv(_first(merged_values, "CORS_ALLOWED_ORIGINS"))
    cors_allowed_origins = []
    for origin in [landing_origin, frontend_origin, *configured_origins, *DEFAULT_LOCAL_ORIGINS]:
        normalized = origin.rstrip("/")
        if normalized and normalized not in cors_allowed_origins:
            cors_allowed_origins.append(normalized)

    trusted_hosts = _split_csv(_first(merged_values, "TRUSTED_HOSTS"))

    return Settings(
        app_name="Kaizen Flow API",
        api_prefix="/api",
        api_base_url=str(_first(merged_values, "ML_API_BASE") or "https://api.mercadolibre.com"),
        auth_base_url=str(_first(merged_values, "ML_AUTH_BASE") or "https://api.mercadolibre.com"),
        oauth_authorize_url=str(
            _first(merged_values, "ML_OAUTH_AUTHORIZE_URL") or "https://auth.mercadolibre.com.ar/authorization"
        ),
        app_id=str(_first(merged_values, "ML_APP_ID") or ""),
        client_secret=str(_first(merged_values, "ML_CLIENT_SECRET") or ""),
        redirect_uri=str(_first(merged_values, "ML_REDIRECT_URI")) if _first(merged_values, "ML_REDIRECT_URI") else None,
        frontend_origin=frontend_origin,
        landing_origin=landing_origin,
        public_app_url=public_app_url,
        cors_allowed_origins=cors_allowed_origins,
        trusted_hosts=trusted_hosts,
        database_url=database_url,
        legacy_database_path=legacy_database_path,
        session_cookie_name=str(_first(merged_values, "SESSION_COOKIE_NAME") or "kaizen_session"),
        session_cookie_secure=_to_bool(_first(merged_values, "SESSION_COOKIE_SECURE"), default=False),
        session_cookie_same_site=_normalize_same_site(_first(merged_values, "SESSION_COOKIE_SAME_SITE"), default="lax"),
        session_cookie_domain=str(_first(merged_values, "SESSION_COOKIE_DOMAIN")).strip()
        if _first(merged_values, "SESSION_COOKIE_DOMAIN")
        else None,
        session_ttl_hours=_to_int(_first(merged_values, "SESSION_TTL_HOURS"), default=24 * 14),
        csrf_cookie_name=str(_first(merged_values, "CSRF_COOKIE_NAME") or "kaizen_csrf"),
        csrf_cookie_secure=_to_bool(_first(merged_values, "CSRF_COOKIE_SECURE"), default=False),
        csrf_cookie_same_site=_normalize_same_site(_first(merged_values, "CSRF_COOKIE_SAME_SITE"), default="lax"),
        csrf_cookie_domain=str(_first(merged_values, "CSRF_COOKIE_DOMAIN")).strip()
        if _first(merged_values, "CSRF_COOKIE_DOMAIN")
        else None,
        encryption_key=str(_first(merged_values, "APP_ENCRYPTION_KEY") or "").strip(),
        password_pepper=str(_first(merged_values, "PASSWORD_PEPPER")).strip()
        if _first(merged_values, "PASSWORD_PEPPER")
        else None,
        auth_rate_limit_requests=_to_int(_first(merged_values, "AUTH_RATE_LIMIT_REQUESTS"), default=8),
        auth_rate_limit_window_seconds=_to_int(_first(merged_values, "AUTH_RATE_LIMIT_WINDOW_SECONDS"), default=60),
        checkout_rate_limit_requests=_to_int(_first(merged_values, "CHECKOUT_RATE_LIMIT_REQUESTS"), default=12),
        checkout_rate_limit_window_seconds=_to_int(
            _first(merged_values, "CHECKOUT_RATE_LIMIT_WINDOW_SECONDS"),
            default=300,
        ),
        security_headers_enabled=_to_bool(_first(merged_values, "SECURITY_HEADERS_ENABLED"), default=True),
        serve_landing_from_backend=_to_bool(_first(merged_values, "SERVE_LANDING_FROM_BACKEND"), default=True),
        default_plan_code=str(_first(merged_values, "DEFAULT_PLAN_CODE") or "growth"),
    )


__all__ = ["AccountCredentials", "ENV_PATH", "ROOT_DIR", "Settings", "_slugify", "get_settings"]
