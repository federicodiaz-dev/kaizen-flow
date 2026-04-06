from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone


PASSWORD_ITERATIONS = 600_000
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


def generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = hashlib.sha256(verifier.encode("utf-8")).digest()
    encoded = base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("=")
    return verifier, encoded
