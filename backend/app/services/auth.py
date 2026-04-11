from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.core.account_store import AccountStore
from app.core.database import Database
from app.core.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConfigurationError,
    MercadoLibreAPIError,
)
from app.core.plan_catalog import DEFAULT_PLAN_CODE
from app.core.security import (
    add_hours,
    generate_pkce_pair,
    generate_session_token,
    hash_password,
    hash_token,
    is_valid_email,
    is_valid_username,
    normalize_username,
    utc_now_iso,
    verify_password,
)
from app.core.settings import Settings
from app.schemas.auth import UserProfile
from app.schemas.plans import PlanCatalogItem, PlanSummary


USER_PROFILE_SELECT = """
SELECT
    users.id,
    users.email,
    users.username,
    users.username_normalized,
    users.created_at,
    users.is_first_visit,
    users.default_account_key,
    plans.code AS plan_code,
    plans.name AS plan_name,
    plans.headline AS plan_headline,
    current_subscription.status AS plan_status,
    plans.price_monthly AS plan_price_monthly,
    plans.currency AS plan_currency,
    plans.max_accounts AS plan_max_accounts,
    plans.reply_assistant_limit AS plan_reply_assistant_limit,
    plans.listing_doctor_limit AS plan_listing_doctor_limit
FROM users
LEFT JOIN user_plan_subscriptions AS current_subscription
  ON current_subscription.user_id = users.id
 AND current_subscription.ended_at IS NULL
LEFT JOIN plans
  ON plans.code = current_subscription.plan_code
"""


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: int
    email: str
    username: str
    created_at: str
    is_first_visit: bool = False
    default_account: str | None = None
    current_plan: PlanSummary | None = None

    def to_profile(self) -> UserProfile:
        return UserProfile(
            id=self.id,
            email=self.email,
            username=self.username,
            created_at=self.created_at,
            is_first_visit=self.is_first_visit,
            default_account=self.default_account,
            current_plan=self.current_plan,
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
        username: str | None,
        password: str,
        selected_plan_code: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[AuthenticatedUser, str]:
        clean_email = email.strip().lower()
        resolved_plan_code = (selected_plan_code or DEFAULT_PLAN_CODE).strip().lower()
        self._validate_credentials(clean_email, password)

        password_hash, password_salt = hash_password(password)
        now = utc_now_iso()

        try:
            with self._database.connect() as connection:
                resolved_username = self._resolve_registration_username(
                    connection,
                    email=clean_email,
                    requested_username=username,
                )
                cursor = connection.execute(
                    """
                    INSERT INTO users (
                        email,
                        username,
                        username_normalized,
                        password_hash,
                        password_salt,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_email,
                        resolved_username,
                        resolved_username,
                        password_hash,
                        password_salt,
                        now,
                        now,
                    ),
                )
                user_id = int(cursor.lastrowid)
                self._replace_current_plan(
                    connection,
                    user_id=user_id,
                    plan_code=resolved_plan_code,
                    source="auth.register",
                    selected_from="auth.register",
                    notes="Plan selected during registration.",
                )
        except sqlite3.IntegrityError as exc:
            message = str(exc).lower()
            if "username_normalized" in message:
                raise BadRequestError("Ese usuario ya existe. Elegi otro username.") from exc
            raise BadRequestError("Ya existe una cuenta registrada con ese email.") from exc

        user = self.get_user_by_id(user_id)
        session_token = self._create_session(user_id, user_agent=user_agent, ip_address=ip_address)
        return user, session_token

    def login_user(
        self,
        *,
        identifier: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[AuthenticatedUser, str]:
        clean_identifier = identifier.strip().lower()
        if not clean_identifier:
            raise AuthenticationError("Ingresa tu email o username.")

        with self._database.connect() as connection:
            row = connection.execute(
                f"""
                {USER_PROFILE_SELECT}
                WHERE lower(users.email) = ? OR users.username_normalized = ?
                LIMIT 1
                """,
                (clean_identifier, clean_identifier),
            ).fetchone()
            password_row = connection.execute(
                """
                SELECT password_hash, password_salt
                FROM users
                WHERE lower(email) = ? OR username_normalized = ?
                LIMIT 1
                """,
                (clean_identifier, clean_identifier),
            ).fetchone()

        if (
            row is None
            or password_row is None
            or not verify_password(
                password,
                salt=str(password_row["password_salt"]),
                expected_hash=str(password_row["password_hash"]),
            )
        ):
            raise AuthenticationError("Email, username o contrasena incorrectos.")

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
                f"""
                {USER_PROFILE_SELECT}
                JOIN user_sessions
                  ON user_sessions.user_id = users.id
                WHERE user_sessions.token_hash = ?
                  AND user_sessions.expires_at > ?
                LIMIT 1
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
                f"""
                {USER_PROFILE_SELECT}
                WHERE users.id = ?
                LIMIT 1
                """,
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

    def complete_onboarding(self, user_id: int) -> AuthenticatedUser:
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE users SET is_first_visit = 0, updated_at = ? WHERE id = ?",
                (utc_now_iso(), user_id),
            )
        return self.get_user_by_id(user_id)

    def list_public_plans(self) -> list[PlanCatalogItem]:
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    code,
                    name,
                    headline,
                    description,
                    price_monthly,
                    currency,
                    max_accounts,
                    reply_assistant_limit,
                    listing_doctor_limit,
                    features_json,
                    sort_order
                FROM plans
                WHERE is_public = 1
                ORDER BY sort_order, price_monthly, name
                """
            ).fetchall()
        return [self._plan_catalog_row_to_item(row) for row in rows]

    def select_plan(
        self,
        *,
        user_id: int,
        plan_code: str,
        source: str = "plans.select",
        selected_from: str = "api.plans.select",
    ) -> AuthenticatedUser:
        with self._database.connect() as connection:
            self._replace_current_plan(
                connection,
                user_id=user_id,
                plan_code=plan_code.strip().lower(),
                source=source,
                selected_from=selected_from,
                notes="Plan selected from self-service flow.",
            )
        return self.get_user_by_id(user_id)

    def build_mercadolibre_authorization_url(
        self,
        *,
        user_id: int,
        requested_account_key: str | None = None,
        requested_label: str | None = None,
        return_origin: str | None = None,
    ) -> str:
        if not self._settings.app_id or not self._settings.client_secret or not self._settings.redirect_uri:
            raise ConfigurationError(
                "Mercado Libre OAuth no esta configurado. Revisa ML_APP_ID, ML_CLIENT_SECRET y ML_REDIRECT_URI."
            )

        state = generate_session_token()
        verifier, challenge = generate_pkce_pair()
        now = utc_now_iso()

        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO oauth_states (
                    state, user_id, requested_account_key, requested_label, return_origin, code_verifier, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state,
                    user_id,
                    requested_account_key.strip() if requested_account_key else None,
                    requested_label.strip() if requested_label else None,
                    return_origin.strip().rstrip("/") if return_origin else None,
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
                "Mercado Libre rechazo la autorizacion.",
                details={"error": error, "error_description": error_description},
            )
        if not code or not state:
            raise BadRequestError("La respuesta de autorizacion de Mercado Libre es invalida.")

        with self._database.connect() as connection:
            oauth_row = connection.execute(
                """
                SELECT state, user_id, requested_account_key, requested_label, return_origin, code_verifier, expires_at
                FROM oauth_states
                WHERE state = ?
                """,
                (state,),
            ).fetchone()

        if oauth_row is None:
            raise BadRequestError("La sesion de autorizacion ya no es valida. Vuelve a intentarlo.")

        if str(oauth_row["expires_at"]) <= utc_now_iso():
            with self._database.connect() as connection:
                connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            raise BadRequestError("La autorizacion de Mercado Libre expiro. Vuelve a intentarlo.")

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
            raise ConfigurationError("Mercado Libre no devolvio el user_id autenticado.")

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
            is_active_for_new=True,
            is_active_for_existing=True,
        )

        with self._database.connect() as connection:
            connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))

        return {
            "user_id": int(oauth_row["user_id"]),
            "account_key": linked_account.key,
            "account_label": linked_account.label,
            "ml_user_id": linked_account.user_id,
            "frontend_origin": str(oauth_row["return_origin"] or self._settings.frontend_origin).rstrip("/"),
        }

    def get_oauth_frontend_origin(self, state: str | None) -> str | None:
        if not state:
            return None

        with self._database.connect() as connection:
            row = connection.execute(
                """
                SELECT return_origin
                FROM oauth_states
                WHERE state = ?
                LIMIT 1
                """,
                (state,),
            ).fetchone()

        if row is None or not row["return_origin"]:
            return None
        return str(row["return_origin"]).rstrip("/")

    def build_frontend_callback_url(
        self,
        *,
        success: bool,
        account_key: str | None = None,
        message: str | None = None,
        frontend_origin: str | None = None,
    ) -> str:
        status = "success" if success else "error"
        resolved_frontend_origin = self._settings.frontend_callback_origin
        url = f"{resolved_frontend_origin}/auth/mercadolibre/callback?status={status}"
        if account_key:
            url += f"&account={quote_plus(account_key)}"
        if message:
            url += f"&message={quote_plus(message)}"
        return url

    def _resolve_registration_username(
        self,
        connection: sqlite3.Connection,
        *,
        email: str,
        requested_username: str | None,
    ) -> str:
        if requested_username and requested_username.strip():
            normalized = normalize_username(requested_username)
            if not is_valid_username(requested_username):
                raise BadRequestError(
                    "El username debe tener entre 3 y 40 caracteres y solo puede usar letras, numeros, punto, guion o guion bajo."
                )
            existing = connection.execute(
                "SELECT 1 FROM users WHERE username_normalized = ? LIMIT 1",
                (normalized,),
            ).fetchone()
            if existing is not None:
                raise BadRequestError("Ese usuario ya existe. Elegi otro username.")
            return normalized

        email_local_part = email.partition("@")[0]
        generated = normalize_username(email_local_part) or DEFAULT_PLAN_CODE
        return self._generate_unique_username(connection, generated)

    def _generate_unique_username(
        self,
        connection: sqlite3.Connection,
        base_username: str,
    ) -> str:
        normalized_base = normalize_username(base_username) or "user"
        candidate = normalized_base
        suffix = 1

        while True:
            row = connection.execute(
                "SELECT 1 FROM users WHERE username_normalized = ? LIMIT 1",
                (candidate,),
            ).fetchone()
            if row is None:
                return candidate

            suffix += 1
            suffix_text = f"_{suffix}"
            trimmed = normalized_base[: max(1, 40 - len(suffix_text))]
            candidate = f"{trimmed}{suffix_text}"

    def _replace_current_plan(
        self,
        connection: sqlite3.Connection,
        *,
        user_id: int,
        plan_code: str,
        source: str,
        selected_from: str,
        notes: str,
    ) -> None:
        normalized_plan_code = plan_code.strip().lower()
        plan_exists = connection.execute(
            "SELECT code FROM plans WHERE code = ? LIMIT 1",
            (normalized_plan_code,),
        ).fetchone()
        if plan_exists is None:
            raise BadRequestError("El plan seleccionado no existe.")

        now = utc_now_iso()
        current_subscription = connection.execute(
            """
            SELECT id, plan_code, status
            FROM user_plan_subscriptions
            WHERE user_id = ?
              AND ended_at IS NULL
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()

        if current_subscription is not None and str(current_subscription["plan_code"]) == normalized_plan_code:
            connection.execute(
                """
                UPDATE user_plan_subscriptions
                SET updated_at = ?, selected_from = ?, notes = ?
                WHERE id = ?
                """,
                (now, selected_from, notes, int(current_subscription["id"])),
            )
            connection.execute(
                """
                INSERT INTO user_plan_events (
                    user_id,
                    subscription_id,
                    plan_code,
                    event_type,
                    source,
                    payload_json,
                    created_at
                ) VALUES (?, ?, ?, 'reselected', ?, ?, ?)
                """,
                (
                    user_id,
                    int(current_subscription["id"]),
                    normalized_plan_code,
                    source,
                    json.dumps({"selected_from": selected_from}),
                    now,
                ),
            )
            return

        previous_subscription_id: int | None = None
        previous_plan_code: str | None = None
        if current_subscription is not None:
            previous_subscription_id = int(current_subscription["id"])
            previous_plan_code = str(current_subscription["plan_code"])
            connection.execute(
                """
                UPDATE user_plan_subscriptions
                SET status = 'canceled', ended_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, previous_subscription_id),
            )

        cursor = connection.execute(
            """
            INSERT INTO user_plan_subscriptions (
                user_id,
                plan_code,
                status,
                source,
                started_at,
                selected_from,
                notes,
                created_at,
                updated_at
            ) VALUES (?, ?, 'selected', ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                normalized_plan_code,
                source,
                now,
                selected_from,
                notes,
                now,
                now,
            ),
        )
        subscription_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO user_plan_events (
                user_id,
                subscription_id,
                plan_code,
                event_type,
                source,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, 'selected', ?, ?, ?)
            """,
            (
                user_id,
                subscription_id,
                normalized_plan_code,
                source,
                json.dumps(
                    {
                        "selected_from": selected_from,
                        "previous_plan_code": previous_plan_code,
                        "previous_subscription_id": previous_subscription_id,
                    }
                ),
                now,
            ),
        )

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
            raise BadRequestError("Ingresa un email valido.")
        if len(password) < 8:
            raise BadRequestError("La contrasena debe tener al menos 8 caracteres.")

    def _row_to_user(self, row: sqlite3.Row) -> AuthenticatedUser:
        return AuthenticatedUser(
            id=int(row["id"]),
            email=str(row["email"]),
            username=str(row["username"] or row["username_normalized"] or ""),
            created_at=str(row["created_at"]),
            is_first_visit=bool(row["is_first_visit"]) if "is_first_visit" in row.keys() else False,
            default_account=str(row["default_account_key"]) if row["default_account_key"] else None,
            current_plan=self._row_to_plan_summary(row),
        )

    def _row_to_plan_summary(self, row: sqlite3.Row) -> PlanSummary | None:
        if not row["plan_code"]:
            return None
        return PlanSummary(
            code=str(row["plan_code"]),
            name=str(row["plan_name"]),
            headline=str(row["plan_headline"]),
            status=str(row["plan_status"] or "selected"),
            price_monthly=int(row["plan_price_monthly"]),
            currency=str(row["plan_currency"]),
            max_accounts=int(row["plan_max_accounts"]),
            reply_assistant_limit=(
                int(row["plan_reply_assistant_limit"])
                if row["plan_reply_assistant_limit"] is not None
                else None
            ),
            listing_doctor_limit=(
                int(row["plan_listing_doctor_limit"])
                if row["plan_listing_doctor_limit"] is not None
                else None
            ),
        )

    def _plan_catalog_row_to_item(self, row: sqlite3.Row) -> PlanCatalogItem:
        return PlanCatalogItem(
            code=str(row["code"]),
            name=str(row["name"]),
            headline=str(row["headline"]),
            description=str(row["description"]),
            price_monthly=int(row["price_monthly"]),
            currency=str(row["currency"]),
            max_accounts=int(row["max_accounts"]),
            reply_assistant_limit=(
                int(row["reply_assistant_limit"])
                if row["reply_assistant_limit"] is not None
                else None
            ),
            listing_doctor_limit=(
                int(row["listing_doctor_limit"])
                if row["listing_doctor_limit"] is not None
                else None
            ),
            features=list(json.loads(str(row["features_json"] or "[]"))),
            sort_order=int(row["sort_order"]),
        )
