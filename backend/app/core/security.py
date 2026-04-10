from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from importlib import import_module
from typing import Any

from .exceptions import ConfigurationError


LEGACY_PASSWORD_ITERATIONS = 600_000
CURRENT_PASSWORD_SCHEME = "argon2id"
LEGACY_PASSWORD_SCHEME = "pbkdf2_sha256"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def add_hours(hours: int) -> str:
    return (utc_now() + timedelta(hours=hours)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _apply_password_pepper(password: str, pepper: str | None = None) -> str:
    if not pepper:
        return password
    return f"{password}{pepper}"


def _load_argon2_components() -> tuple[Any, Any]:
    try:
        argon2_module = import_module("argon2")
        low_level = import_module("argon2.low_level")
    except ModuleNotFoundError as exc:
        raise ConfigurationError(
            "argon2-cffi no esta instalado. Instala las dependencias backend antes de usar autenticacion.",
        ) from exc
    return argon2_module, low_level


def _password_hasher() -> Any:
    argon2_module, low_level = _load_argon2_components()
    return argon2_module.PasswordHasher(
        time_cost=3,
        memory_cost=65_536,
        parallelism=4,
        hash_len=32,
        salt_len=16,
        type=low_level.Type.ID,
    )


def hash_password(password: str, *, pepper: str | None = None) -> tuple[str, str | None, str]:
    hasher = _password_hasher()
    return hasher.hash(_apply_password_pepper(password, pepper)), None, CURRENT_PASSWORD_SCHEME


def hash_password_legacy(password: str, salt: str | None = None, *, pepper: str | None = None) -> tuple[str, str, str]:
    resolved_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        _apply_password_pepper(password, pepper).encode("utf-8"),
        resolved_salt.encode("utf-8"),
        LEGACY_PASSWORD_ITERATIONS,
    )
    return base64.b64encode(digest).decode("ascii"), resolved_salt, LEGACY_PASSWORD_SCHEME


def verify_password(
    password: str,
    *,
    expected_hash: str,
    salt: str | None = None,
    scheme: str = CURRENT_PASSWORD_SCHEME,
    pepper: str | None = None,
) -> bool:
    normalized_scheme = (scheme or CURRENT_PASSWORD_SCHEME).strip().lower()
    if normalized_scheme == CURRENT_PASSWORD_SCHEME:
        hasher = _password_hasher()
        try:
            return bool(hasher.verify(expected_hash, _apply_password_pepper(password, pepper)))
        except Exception:
            return False

    if normalized_scheme == LEGACY_PASSWORD_SCHEME:
        actual_hash, _, _ = hash_password_legacy(password, salt=salt, pepper=pepper)
        return hmac.compare_digest(actual_hash, expected_hash)

    return False


def password_needs_rehash(scheme: str | None) -> bool:
    normalized_scheme = (scheme or CURRENT_PASSWORD_SCHEME).strip().lower()
    return normalized_scheme != CURRENT_PASSWORD_SCHEME


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_PATTERN.fullmatch(email.strip()))


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = hashlib.sha256(verifier.encode("utf-8")).digest()
    encoded = base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("=")
    return verifier, encoded


def _fernet_factory(key: str) -> Any:
    try:
        fernet_module = import_module("cryptography.fernet")
    except ModuleNotFoundError as exc:
        raise ConfigurationError(
            "cryptography no esta instalado. Instala las dependencias backend antes de cifrar secretos.",
        ) from exc
    try:
        return fernet_module.Fernet(key.encode("ascii"))
    except Exception as exc:
        raise ConfigurationError("APP_ENCRYPTION_KEY no tiene un formato Fernet valido.") from exc


def encrypt_secret(value: str | None, key: str) -> str | None:
    if not value:
        return None
    if not key:
        raise ConfigurationError("APP_ENCRYPTION_KEY es obligatorio para guardar tokens sensibles.")
    fernet = _fernet_factory(key)
    return fernet.encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None, key: str) -> str | None:
    if not value:
        return None
    if not key:
        raise ConfigurationError("APP_ENCRYPTION_KEY es obligatorio para leer tokens sensibles.")
    fernet = _fernet_factory(key)
    return fernet.decrypt(value.encode("ascii")).decode("utf-8")


def safe_compare(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    return hmac.compare_digest(left, right)
