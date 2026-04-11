from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken


PASSWORD_ITERATIONS = 600_000
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{1,38}[a-z0-9])?$")
TOKEN_PREFIX = "enc:v1:"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def add_hours(hours: int) -> str:
    return (utc_now() + timedelta(hours=hours)).isoformat(timespec="seconds").replace("+00:00", "Z")


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    resolved_salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        resolved_salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    return base64.b64encode(digest).decode("ascii"), resolved_salt


def verify_password(password: str, *, salt: str, expected_hash: str) -> bool:
    actual_hash, _ = hash_password(password, salt=salt)
    return hmac.compare_digest(actual_hash, expected_hash)


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_PATTERN.fullmatch(email.strip()))


def normalize_username(username: str) -> str:
    lowered = username.strip().lower().replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9._-]+", "", lowered)
    normalized = re.sub(r"[._-]{2,}", "_", normalized).strip("._-")
    return normalized[:40]


def is_valid_username(username: str) -> bool:
    normalized = normalize_username(username)
    return bool(USERNAME_PATTERN.fullmatch(normalized))


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = hashlib.sha256(verifier.encode("utf-8")).digest()
    encoded = base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("=")
    return verifier, encoded


def validate_password_strength(password: str) -> str | None:
    if len(password) < 12:
        return "La contrasena debe tener al menos 12 caracteres."
    if not re.search(r"[a-z]", password):
        return "La contrasena debe incluir al menos una letra minuscula."
    if not re.search(r"[A-Z]", password):
        return "La contrasena debe incluir al menos una letra mayuscula."
    if not re.search(r"\d", password):
        return "La contrasena debe incluir al menos un numero."
    if not re.search(r"[^A-Za-z0-9]", password):
        return "La contrasena debe incluir al menos un simbolo."
    return None


class TokenCipher:
    def __init__(self, secret: str | None) -> None:
        normalized_secret = (secret or "").strip()
        self._enabled = bool(normalized_secret)
        self._fernet = Fernet(self._derive_fernet_key(normalized_secret)) if self._enabled else None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def is_encrypted(self, value: str | None) -> bool:
        return bool(value and value.startswith(TOKEN_PREFIX))

    def encrypt(self, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if self.is_encrypted(value):
            return value
        if not self._enabled or self._fernet is None:
            raise ValueError("No se puede cifrar el token sin APP_TOKEN_ENCRYPTION_KEY.")
        ciphertext = self._fernet.encrypt(value.encode("utf-8")).decode("ascii")
        return f"{TOKEN_PREFIX}{ciphertext}"

    def decrypt(self, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        if not self.is_encrypted(value):
            return value
        if not self._enabled or self._fernet is None:
            raise ValueError("No se puede descifrar el token sin APP_TOKEN_ENCRYPTION_KEY.")
        payload = value[len(TOKEN_PREFIX) :]
        try:
            return self._fernet.decrypt(payload.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise ValueError("No se pudo descifrar el token almacenado.") from exc

    def _derive_fernet_key(self, secret: str) -> bytes:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)
