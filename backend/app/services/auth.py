from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus
from uuid import uuid4

import httpx

from app.core.account_store import AccountStore
from app.core.audit import record_audit_event
from app.core.database import Database, DatabaseSession
from app.core.exceptions import AuthenticationError, BadRequestError, ConfigurationError, MercadoLibreAPIError
from app.core.security import (
    add_hours,
    generate_pkce_pair,
    generate_session_token,
    hash_password,
    hash_token,
    is_valid_email,
    password_needs_rehash,
    safe_compare,
    utc_now_iso,
    verify_password,
)
from app.core.settings import Settings, _slugify
from app.schemas.auth import SessionResponse, SubscriptionProfile, UserProfile, WorkspaceProfile


ACTIVE_SUBSCRIPTION_STATUSES = {"active", "trialing"}


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: str
    email: str
    created_at: str
    workspace_id: str
    workspace_name: str
    workspace_slug: str
    workspace_role: str
    subscription_status: str = "inactive"
    subscription_plan_code: str | None = None
    subscription_plan_name: str | None = None
    subscription_started_at: str | None = None
    subscription_updated_at: str | None = None
    subscription_expires_at: str | None = None
    is_first_visit: bool = False
    default_account: str | None = None

    @property
    def has_active_subscription(self) -> bool:
        return self.subscription_status in ACTIVE_SUBSCRIPTION_STATUSES

    def to_profile(self) -> UserProfile:
        return UserProfile(
            id=self.id,
            email=self.email,
            created_at=self.created_at,
            is_first_visit=self.is_first_visit,
            default_account=self.default_account,
        )

    def to_workspace(self) -> WorkspaceProfile:
        return WorkspaceProfile(
            id=self.workspace_id,
            name=self.workspace_name,
            slug=self.workspace_slug,
            role=self.workspace_role,
        )

    def to_subscription(self) -> SubscriptionProfile:
        return SubscriptionProfile(
            status=self.subscription_status,
            plan_code=self.subscription_plan_code,
            plan_name=self.subscription_plan_name,
            started_at=self.subscription_started_at,
            updated_at=self.subscription_updated_at,
            expires_at=self.subscription_expires_at,
            is_active=self.has_active_subscription,
        )

    def to_session_response(self, *, csrf_token: str | None = None) -> SessionResponse:
        return SessionResponse(
            user=self.to_profile(),
            workspace=self.to_workspace(),
            subscription=self.to_subscription(),
            csrf_token=csrf_token,
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
        workspace_name: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
        replaced_session_token: str | None = None,
    ) -> tuple[AuthenticatedUser, str]:
        clean_email = email.strip().lower()
        self._validate_credentials(clean_email, password)

        password_hash, password_salt, password_scheme = hash_password(
            password,
            pepper=self._settings.password_pepper,
        )
        user_id = str(uuid4())
        workspace_id = str(uuid4())
        now = utc_now_iso()

        try:
            with self._database.connect() as connection:
                if connection.fetchone("SELECT 1 FROM users WHERE email = ?", (clean_email,)):
                    raise BadRequestError("Ya existe una cuenta registrada con ese email.")

                resolved_workspace_name = self._derive_workspace_name(clean_email, workspace_name)
                workspace_slug = self._resolve_unique_workspace_slug(connection, resolved_workspace_name)

                connection.execute(
                    """
                    INSERT INTO workspaces (id, slug, name, status, created_at, updated_at)
                    VALUES (?, ?, ?, 'active', ?, ?)
                    """,
                    (workspace_id, workspace_slug, resolved_workspace_name, now, now),
                )
                connection.execute(
                    """
                    INSERT INTO users (
                        id, email, password_hash, password_salt, password_scheme, is_first_visit,
                        default_account_key, primary_workspace_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, TRUE, NULL, ?, ?, ?)
                    """,
                    (
                        user_id,
                        clean_email,
                        password_hash,
                        password_salt,
                        password_scheme,
                        workspace_id,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO workspace_members (
                        id, workspace_id, user_id, role, is_owner, created_at, updated_at
                    ) VALUES (?, ?, ?, 'owner', TRUE, ?, ?)
                    """,
                    (str(uuid4()), workspace_id, user_id, now, now),
                )
                record_audit_event(
                    self._database,
                    event_type="auth.registered",
                    workspace_id=workspace_id,
                    user_id=user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata={"email": clean_email},
                    connection=connection,
                )
                session_token = self._create_session(
                    connection=connection,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    user_agent=user_agent,
                    ip_address=ip_address,
                    replaced_session_token=replaced_session_token,
                )
        except BadRequestError:
            raise
        except Exception as exc:
            if self._database.is_unique_violation(exc):
                raise BadRequestError("Ya existe una cuenta registrada con ese email.") from exc
            raise

        user = self.get_user_by_id(user_id)
        return user, session_token

    def login_user(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None = None,
        ip_address: str | None = None,
        replaced_session_token: str | None = None,
    ) -> tuple[AuthenticatedUser, str]:
        clean_email = email.strip().lower()
        with self._database.connect() as connection:
            row = self._fetch_user_row_by_email(connection, clean_email, include_password=True)

            if row is None or not verify_password(
                password,
                salt=str(row["password_salt"]) if row.get("password_salt") else None,
                expected_hash=str(row["password_hash"]),
                scheme=str(row["password_scheme"] or "argon2id"),
                pepper=self._settings.password_pepper,
            ):
                record_audit_event(
                    self._database,
                    event_type="auth.login_failed",
                    workspace_id=str(row["workspace_id"]) if row else None,
                    user_id=str(row["id"]) if row else None,
                    severity="warning",
                    ip_address=ip_address,
                    user_agent=user_agent,
                    metadata={"email": clean_email},
                    connection=connection,
                )
                raise AuthenticationError("Email o contrasena incorrectos.")

            if password_needs_rehash(str(row["password_scheme"] or "")):
                new_hash, new_salt, new_scheme = hash_password(
                    password,
                    pepper=self._settings.password_pepper,
                )
                connection.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, password_salt = ?, password_scheme = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_hash, new_salt, new_scheme, utc_now_iso(), str(row["id"])),
                )

            connection.execute(
                "UPDATE users SET last_login_at = ?, updated_at = ? WHERE id = ?",
                (utc_now_iso(), utc_now_iso(), str(row["id"])),
            )
            record_audit_event(
                self._database,
                event_type="auth.logged_in",
                workspace_id=str(row["workspace_id"]),
                user_id=str(row["id"]),
                ip_address=ip_address,
                user_agent=user_agent,
                connection=connection,
            )
            session_token = self._create_session(
                connection=connection,
                user_id=str(row["id"]),
                workspace_id=str(row["workspace_id"]),
                user_agent=user_agent,
                ip_address=ip_address,
                replaced_session_token=replaced_session_token,
            )

        user = self.get_user_by_id(str(row["id"]))
        return user, session_token

    def get_user_by_session(self, session_token: str | None) -> AuthenticatedUser:
        if not session_token:
            raise AuthenticationError()

        token_hash = hash_token(session_token)
        now = utc_now_iso()
        with self._database.connect() as connection:
            row = connection.fetchone(
                f"""
                {self._base_user_select(include_password=False)}
                JOIN auth_sessions ON auth_sessions.user_id = users.id
                    AND auth_sessions.workspace_id = users.primary_workspace_id
                WHERE auth_sessions.token_hash = ? AND auth_sessions.expires_at > ?
                """,
                (token_hash, now),
            )

            if row is None:
                connection.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
                raise AuthenticationError()

            connection.execute(
                "UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )

        return self._row_to_user(row)

    def get_user_by_id(self, user_id: str) -> AuthenticatedUser:
        with self._database.connect() as connection:
            row = connection.fetchone(
                f"""
                {self._base_user_select(include_password=False)}
                WHERE users.id = ?
                """,
                (user_id,),
            )
        if row is None:
            raise AuthenticationError()
        return self._row_to_user(row)

    def logout(
        self,
        session_token: str | None,
        *,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> None:
        if not session_token:
            return
        token_hash = hash_token(session_token)
        with self._database.connect() as connection:
            row = connection.fetchone(
                """
                SELECT id, user_id, workspace_id
                FROM auth_sessions
                WHERE token_hash = ?
                """,
                (token_hash,),
            )
            connection.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (token_hash,))
            if row:
                record_audit_event(
                    self._database,
                    event_type="auth.logged_out",
                    workspace_id=str(row["workspace_id"]),
                    user_id=str(row["user_id"]),
                    ip_address=ip_address,
                    user_agent=user_agent,
                    connection=connection,
                )

    def rotate_session(
        self,
        *,
        current_session_token: str | None,
        user: AuthenticatedUser,
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> str:
        with self._database.connect() as connection:
            return self._create_session(
                connection=connection,
                user_id=user.id,
                workspace_id=user.workspace_id,
                user_agent=user_agent,
                ip_address=ip_address,
                replaced_session_token=current_session_token,
            )

    def set_default_account(self, user_id: str, workspace_id: str, account_key: str) -> None:
        account_store = AccountStore(
            self._database,
            user_id=user_id,
            workspace_id=workspace_id,
            encryption_key=self._settings.encryption_key,
        )
        account_store.set_default_account(account_key)

    def complete_onboarding(self, user_id: str) -> AuthenticatedUser:
        with self._database.connect() as connection:
            connection.execute(
                "UPDATE users SET is_first_visit = FALSE, updated_at = ? WHERE id = ?",
                (utc_now_iso(), user_id),
            )
        return self.get_user_by_id(user_id)

    def build_mercadolibre_authorization_url(
        self,
        *,
        user_id: str,
        workspace_id: str,
        requested_account_key: str | None = None,
        requested_label: str | None = None,
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
                    state, user_id, workspace_id, requested_account_key, requested_label,
                    code_verifier, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state,
                    user_id,
                    workspace_id,
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
                "Mercado Libre rechazo la autorizacion.",
                details={"error": error, "error_description": error_description},
            )
        if not code or not state:
            raise BadRequestError("La respuesta de autorizacion de Mercado Libre es invalida.")

        with self._database.connect() as connection:
            oauth_row = connection.fetchone(
                """
                SELECT state, user_id, workspace_id, requested_account_key, requested_label, code_verifier, expires_at
                FROM oauth_states
                WHERE state = ?
                """,
                (state,),
            )

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

        account_store = AccountStore(
            self._database,
            user_id=str(oauth_row["user_id"]),
            workspace_id=str(oauth_row["workspace_id"]),
            encryption_key=self._settings.encryption_key,
        )
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
        )

        with self._database.connect() as connection:
            connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            record_audit_event(
                self._database,
                event_type="ml.account_connected",
                workspace_id=str(oauth_row["workspace_id"]),
                user_id=str(oauth_row["user_id"]),
                entity_type="ml_account",
                entity_id=linked_account.key,
                metadata={"ml_user_id": linked_account.user_id, "label": linked_account.label},
                connection=connection,
            )

        return {
            "user_id": str(oauth_row["user_id"]),
            "workspace_id": str(oauth_row["workspace_id"]),
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
        *,
        connection: DatabaseSession,
        user_id: str,
        workspace_id: str,
        user_agent: str | None,
        ip_address: str | None,
        replaced_session_token: str | None = None,
    ) -> str:
        session_token = generate_session_token()
        rotated_from_session_id = None
        if replaced_session_token:
            existing_session = connection.fetchone(
                "SELECT id FROM auth_sessions WHERE token_hash = ?",
                (hash_token(replaced_session_token),),
            )
            if existing_session:
                rotated_from_session_id = str(existing_session["id"])
                connection.execute(
                    "DELETE FROM auth_sessions WHERE token_hash = ?",
                    (hash_token(replaced_session_token),),
                )

        connection.execute(
            """
            INSERT INTO auth_sessions (
                id, user_id, workspace_id, token_hash, created_at, expires_at, last_seen_at,
                user_agent, ip_address, rotated_from_session_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                user_id,
                workspace_id,
                hash_token(session_token),
                utc_now_iso(),
                add_hours(self._settings.session_ttl_hours),
                utc_now_iso(),
                user_agent,
                ip_address,
                rotated_from_session_id,
            ),
        )
        return session_token

    def _validate_credentials(self, email: str, password: str) -> None:
        if not is_valid_email(email):
            raise BadRequestError("Ingresa un email valido.")
        if len(password) < 8:
            raise BadRequestError("La contrasena debe tener al menos 8 caracteres.")

    def _derive_workspace_name(self, email: str, workspace_name: str | None) -> str:
        if workspace_name and workspace_name.strip():
            return workspace_name.strip()
        local_part = email.split("@", 1)[0].strip() or "Workspace"
        return local_part.replace(".", " ").replace("_", " ").strip().title() or "Workspace"

    def _resolve_unique_workspace_slug(self, connection: DatabaseSession, workspace_name: str) -> str:
        base_slug = _slugify(workspace_name)
        candidate = base_slug
        suffix = 2
        while connection.fetchone("SELECT 1 FROM workspaces WHERE slug = ?", (candidate,)):
            candidate = f"{base_slug}-{suffix}"
            suffix += 1
        return candidate

    def _fetch_user_row_by_email(
        self,
        connection: DatabaseSession,
        email: str,
        *,
        include_password: bool,
    ) -> dict[str, Any] | None:
        return connection.fetchone(
            f"""
            {self._base_user_select(include_password=include_password)}
            WHERE users.email = ?
            """,
            (email,),
        )

    def _base_user_select(self, *, include_password: bool) -> str:
        password_fields = """
            users.password_hash,
            users.password_salt,
            users.password_scheme,
        """ if include_password else ""

        return f"""
            SELECT
                users.id,
                users.email,
                {password_fields}
                users.created_at,
                users.is_first_visit,
                users.default_account_key,
                workspaces.id AS workspace_id,
                workspaces.name AS workspace_name,
                workspaces.slug AS workspace_slug,
                workspace_members.role AS workspace_role,
                latest_subscription.plan_code AS subscription_plan_code,
                latest_subscription.status AS subscription_status,
                latest_subscription.started_at AS subscription_started_at,
                latest_subscription.updated_at AS subscription_updated_at,
                latest_subscription.expires_at AS subscription_expires_at,
                subscription_plans.name AS subscription_plan_name
            FROM users
            JOIN workspaces ON workspaces.id = users.primary_workspace_id
            JOIN workspace_members
                ON workspace_members.workspace_id = users.primary_workspace_id
                AND workspace_members.user_id = users.id
            LEFT JOIN LATERAL (
                SELECT
                    workspace_subscriptions.plan_code,
                    workspace_subscriptions.status,
                    workspace_subscriptions.started_at,
                    workspace_subscriptions.updated_at,
                    workspace_subscriptions.expires_at
                FROM workspace_subscriptions
                WHERE workspace_subscriptions.workspace_id = users.primary_workspace_id
                ORDER BY
                    CASE
                        WHEN workspace_subscriptions.status = 'active' THEN 0
                        WHEN workspace_subscriptions.status = 'trialing' THEN 1
                        ELSE 2
                    END,
                    workspace_subscriptions.updated_at DESC
                LIMIT 1
            ) AS latest_subscription ON TRUE
            LEFT JOIN subscription_plans ON subscription_plans.code = latest_subscription.plan_code
        """

    def _row_to_user(self, row: dict[str, Any]) -> AuthenticatedUser:
        subscription_status = str(row["subscription_status"]) if row.get("subscription_status") else "inactive"
        return AuthenticatedUser(
            id=str(row["id"]),
            email=str(row["email"]),
            created_at=str(row["created_at"]),
            workspace_id=str(row["workspace_id"]),
            workspace_name=str(row["workspace_name"]),
            workspace_slug=str(row["workspace_slug"]),
            workspace_role=str(row.get("workspace_role") or "owner"),
            subscription_status=subscription_status,
            subscription_plan_code=str(row["subscription_plan_code"]) if row.get("subscription_plan_code") else None,
            subscription_plan_name=str(row["subscription_plan_name"]) if row.get("subscription_plan_name") else None,
            subscription_started_at=str(row["subscription_started_at"]) if row.get("subscription_started_at") else None,
            subscription_updated_at=str(row["subscription_updated_at"]) if row.get("subscription_updated_at") else None,
            subscription_expires_at=str(row["subscription_expires_at"]) if row.get("subscription_expires_at") else None,
            is_first_visit=bool(row["is_first_visit"]) if row.get("is_first_visit") is not None else False,
            default_account=str(row["default_account_key"]) if row.get("default_account_key") else None,
        )
