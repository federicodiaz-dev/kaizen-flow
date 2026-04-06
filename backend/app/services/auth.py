from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.core.account_store import AccountStore
from app.core.database import Database
from app.core.exceptions import AuthenticationError, BadRequestError, ConfigurationError, MercadoLibreAPIError
from app.core.security import (
    add_hours,
    generate_pkce_pair,
    generate_session_token,
    hash_password,
    hash_token,
    is_valid_email,
    utc_now,
    utc_now_iso,
    verify_password,
)
from app.core.settings import Settings
from app.schemas.auth import UserProfile


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: int
    email: str
    created_at: str
    default_account: str | None = None

    def to_profile(self) -> UserProfile:
        return UserProfile(
            id=self.id,
            email=self.email,
            created_at=self.created_at,
            default_account=self.default_account,
        )


class AuthService:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._database = database
        self._settings = settings
        self._http_client = http_client

    def register_user(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[AuthenticatedUser, str]:
        clean_email = email.strip().lower()
        self._validate_credentials(clean_email, password)

        password_hash, password_salt = hash_password(password)
        now = utc_now_iso()

        try:
            with self._database.connect() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO users (email, password_hash, password_salt, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (clean_email, password_hash, password_salt, now, now),
                )
                user_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise BadRequestError("Ya existe una cuenta registrada con ese email.") from exc

        user = self.get_user_by_id(user_id)
        session_token = self._create_session(user_id, user_agent=user_agent, ip_address=ip_address)
        return user, session_token

    def login_user(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[AuthenticatedUser, str]:
        clean_email = email.strip().lower()
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT id, email, password_hash, password_salt, created_at, default_account_key
                FROM users
                WHERE email = ?
                """,
                (clean_email,),
            ).fetchone()

        if row is None or not verify_password(
            password,
            salt=str(row["password_salt"]),
            expected_hash=str(row["password_hash"]),
        ):
            raise AuthenticationError("Email o contraseña incorrectos.")

        user = self._row_to_user(row)
        session_token = self._create_session(user.id, user_agent=user_agent, ip_address=ip_address)
        return user, session_token

    def get_user_by_session(self, session_token: str | None) -> AuthenticatedUser:
        if not session_token:
            raise AuthenticationError()

        token_hash = hash_token(session_token)
        now = utc_now_iso()
        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT users.id, users.email, users.created_at, users.default_account_key
                FROM user_sessions
                JOIN users ON users.id = user_sessions.user_id
                WHERE user_sessions.token_hash = ? AND user_sessions.expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()

            if row is None:
                connection.execute("DELETE FROM user_sessions WHERE token_hash = ?", (token_hash,))
                raise AuthenticationError()

            connection.execute(
                "UPDATE user_sessions SET last_seen_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )

        return self._row_to_user(row)

    def get_user_by_id(self, user_id: int) -> AuthenticatedUser:
        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT id, email, created_at, default_account_key FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            raise AuthenticationError()
        return self._row_to_user(row)

    def logout(self, session_token: str | None) -> None:
        if not session_token:
            return
        with self._database.connect() as connection:
            connection.execute("DELETE FROM user_sessions WHERE token_hash = ?", (hash_token(session_token),))

    def set_default_account(self, user_id: int, account_key: str) -> None:
        account_store = AccountStore(self._database, user_id)
        account_store.set_default_account(account_key)

    def build_mercadolibre_authorization_url(
        self,
        *,
        user_id: int,
        requested_account_key: str | None = None,
        requested_label: str | None = None,
    ) -> str:
        if not self._settings.app_id or not self._settings.client_secret or not self._settings.redirect_uri:
            raise ConfigurationError(
                "Mercado Libre OAuth no está configurado. Revisá ML_APP_ID, ML_CLIENT_SECRET y ML_REDIRECT_URI."
            )

        state = generate_session_token()
        verifier, challenge = generate_pkce_pair()
        now = utc_now_iso()

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_states (
                    state, user_id, requested_account_key, requested_label, code_verifier, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state,
                    user_id,
                    requested_account_key.strip() if requested_account_key else None,
                    requested_label.strip() if requested_label else None,
                    verifier,
                    now,
                    add_hours(1),
                ),
            )

        return (
            f"{self._settings.oauth_authorize_url}"
            f"?response_type=code"
            f"&client_id={quote_plus(self._settings.app_id)}"
            f"&redirect_uri={quote_plus(self._settings.redirect_uri)}"
            f"&state={quote_plus(state)}"
            f"&code_challenge={quote_plus(challenge)}"
            f"&code_challenge_method=S256"
        )

    async def complete_mercadolibre_oauth(
        self,
        *,
        code: str | None,
        state: str | None,
        error: str | None = None,
        error_description: str | None = None,
    ) -> dict[str, Any]:
        if error:
            raise BadRequestError(
                "Mercado Libre rechazó la autorización.",
                details={"error": error, "error_description": error_description},
            )
        if not code or not state:
            raise BadRequestError("La respuesta de autorización de Mercado Libre es inválida.")

        with self._database.connect() as connection:
            oauth_row = connection.execute(
                """
                SELECT state, user_id, requested_account_key, requested_label, code_verifier, expires_at
                FROM oauth_states
                WHERE state = ?
                """,
                (state,),
            ).fetchone()

        if oauth_row is None:
            raise BadRequestError("La sesión de autorización ya no es válida. Volvé a intentarlo.")

        if str(oauth_row["expires_at"]) <= utc_now_iso():
            with self._database.connect() as connection:
                connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            raise BadRequestError("La autorización de Mercado Libre expiró. Volvé a intentarlo.")

        token_payload = {
            "grant_type": "authorization_code",
            "client_id": self._settings.app_id,
            "client_secret": self._settings.client_secret,
            "code": code,
            "redirect_uri": self._settings.redirect_uri,
            "code_verifier": str(oauth_row["code_verifier"] or ""),
        }
        token_response = await self._http_client.post(
            f"{self._settings.auth_base_url.rstrip('/')}/oauth/token",
            data=token_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded", "accept": "application/json"},
        )
        if token_response.is_error:
            raise MercadoLibreAPIError.from_response(token_response)

        token_data = token_response.json()
        access_token = str(token_data["access_token"])
        refresh_token = str(token_data.get("refresh_token")) if token_data.get("refresh_token") else None
        scope = str(token_data.get("scope")) if token_data.get("scope") else None
        ml_user_id = int(token_data["user_id"]) if token_data.get("user_id") else None
        if ml_user_id is None:
            raise ConfigurationError("Mercado Libre no devolvió el user_id autenticado.")

        me_response = await self._http_client.get(
            f"{self._settings.api_base_url.rstrip('/')}/users/me",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if me_response.is_error:
            raise MercadoLibreAPIError.from_response(me_response)

        me_data = me_response.json()
        nickname = str(me_data.get("nickname") or "").strip() or None
        site_id = str(me_data.get("site_id") or me_data.get("country_id") or "").strip() or None
        label = str(oauth_row["requested_label"] or nickname or f"Cuenta {ml_user_id}")

        account_store = AccountStore(self._database, int(oauth_row["user_id"]))
        linked_account = account_store.upsert_account(
            ml_user_id=ml_user_id,
            label=label,
            access_token=access_token,
            refresh_token=refresh_token,
            scope=scope,
            nickname=nickname,
            site_id=site_id,
            requested_key=str(oauth_row["requested_account_key"] or "").strip() or None,
            source="oauth",
            is_active_for_new=False,
        )

        with self._database.connect() as connection:
            connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))

        return {
            "user_id": int(oauth_row["user_id"]),
            "account_key": linked_account.key,
            "account_label": linked_account.label,
            "ml_user_id": linked_account.user_id,
        }

    def build_frontend_callback_url(
        self,
        *,
        success: bool,
        account_key: str | None = None,
        message: str | None = None,
    ) -> str:
        status = "success" if success else "error"
        url = f"{self._settings.frontend_origin.rstrip('/')}/auth/mercadolibre/callback?status={status}"
        if account_key:
            url += f"&account={quote_plus(account_key)}"
        if message:
            url += f"&message={quote_plus(message)}"
        return url

    def _create_session(
        self,
        user_id: int,
        *,
        user_agent: str | None,
        ip_address: str | None,
    ) -> str:
        session_token = generate_session_token()
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO user_sessions (
                    user_id, token_hash, created_at, expires_at, last_seen_at, user_agent, ip_address
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    hash_token(session_token),
                    utc_now_iso(),
                    add_hours(self._settings.session_ttl_hours),
                    utc_now_iso(),
                    user_agent,
                    ip_address,
                ),
            )
        return session_token

    def _validate_credentials(self, email: str, password: str) -> None:
        if not is_valid_email(email):
            raise BadRequestError("Ingresá un email válido.")
        if len(password) < 8:
            raise BadRequestError("La contraseña debe tener al menos 8 caracteres.")

    def _row_to_user(self, row: sqlite3.Row) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=int(row["id"]),
            email=str(row["email"]),
            created_at=str(row["created_at"]),
            default_account=str(row["default_account_key"]) if row["default_account_key"] else None,
        )
