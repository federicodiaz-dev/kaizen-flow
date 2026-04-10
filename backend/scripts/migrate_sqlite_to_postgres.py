from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "backend"))

from app.core.database import Database
from app.core.security import encrypt_secret, utc_now_iso
from app.core.settings import _slugify, get_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate Kaizen Flow legacy SQLite data into PostgreSQL.")
    parser.add_argument("--dry-run", action="store_true", help="Inspect legacy data without writing to PostgreSQL.")
    parser.add_argument(
        "--plan-code",
        default=None,
        help="Plan code to apply to migrated workspaces that had active legacy access. Defaults to DEFAULT_PLAN_CODE.",
    )
    return parser.parse_args()


def load_legacy_rows(sqlite_path: Path) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    connection = sqlite3.connect(sqlite_path)
    connection.row_factory = sqlite3.Row
    try:
        users = connection.execute(
            """
            SELECT id, email, password_hash, password_salt, is_first_visit, default_account_key, created_at, updated_at
            FROM users
            ORDER BY id ASC
            """
        ).fetchall()
        accounts = connection.execute(
            """
            SELECT user_id, account_key, label, ml_user_id, nickname, site_id, access_token, refresh_token, scope, source, is_active, created_at, updated_at
            FROM ml_accounts
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        connection.close()
    return list(users), list(accounts)


def derive_workspace_name(email: str) -> str:
    local_part = email.split("@", 1)[0].strip() or "Workspace"
    return local_part.replace(".", " ").replace("_", " ").strip().title() or "Workspace"


def resolve_unique_workspace_slug(connection, proposed_name: str) -> str:
    base_slug = _slugify(proposed_name)
    candidate = base_slug
    suffix = 2
    while connection.fetchone("SELECT 1 FROM workspaces WHERE slug = ?", (candidate,)):
        candidate = f"{base_slug}-{suffix}"
        suffix += 1
    return candidate


def main() -> int:
    args = parse_args()
    settings = get_settings()
    sqlite_path = settings.legacy_database_path

    if not sqlite_path.exists():
        print(f"Legacy SQLite file not found at {sqlite_path}. Nothing to migrate.")
        return 0

    users, accounts = load_legacy_rows(sqlite_path)
    print(f"Legacy users: {len(users)}")
    print(f"Legacy ML accounts: {len(accounts)}")

    if args.dry_run:
        print("Dry run complete. No PostgreSQL changes were made.")
        return 0

    database = Database(settings.database_url)
    database.initialize()

    accounts_by_user: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for account in accounts:
        accounts_by_user[int(account["user_id"])].append(account)

    migrated_users = 0
    migrated_accounts = 0
    activated_workspaces = 0
    target_plan_code = (args.plan_code or settings.default_plan_code).strip().lower()

    with database.connect() as connection:
        for legacy_user in users:
            email = str(legacy_user["email"]).strip().lower()
            existing_user = connection.fetchone(
                "SELECT id, primary_workspace_id FROM users WHERE email = ?",
                (email,),
            )

            if existing_user:
                user_id = str(existing_user["id"])
                workspace_id = str(existing_user["primary_workspace_id"])
            else:
                user_id = str(uuid4())
                workspace_id = str(uuid4())
                workspace_name = derive_workspace_name(email)
                now = utc_now_iso()
                connection.execute(
                    """
                    INSERT INTO workspaces (id, slug, name, status, created_at, updated_at)
                    VALUES (?, ?, ?, 'active', ?, ?)
                    """,
                    (
                        workspace_id,
                        resolve_unique_workspace_slug(connection, workspace_name),
                        workspace_name,
                        str(legacy_user["created_at"] or now),
                        str(legacy_user["updated_at"] or now),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO users (
                        id, email, password_hash, password_salt, password_scheme, is_first_visit,
                        default_account_key, primary_workspace_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pbkdf2_sha256', ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        email,
                        str(legacy_user["password_hash"]),
                        str(legacy_user["password_salt"]),
                        bool(legacy_user["is_first_visit"]),
                        str(legacy_user["default_account_key"]) if legacy_user["default_account_key"] else None,
                        workspace_id,
                        str(legacy_user["created_at"] or now),
                        str(legacy_user["updated_at"] or now),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO workspace_members (
                        id, workspace_id, user_id, role, is_owner, created_at, updated_at
                    ) VALUES (?, ?, ?, 'owner', TRUE, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        workspace_id,
                        user_id,
                        str(legacy_user["created_at"] or now),
                        str(legacy_user["updated_at"] or now),
                    ),
                )
                migrated_users += 1

            legacy_user_accounts = accounts_by_user.get(int(legacy_user["id"]), [])
            legacy_had_active_access = any(bool(account["is_active"]) for account in legacy_user_accounts)

            if legacy_had_active_access:
                existing_active_subscription = connection.fetchone(
                    """
                    SELECT id
                    FROM workspace_subscriptions
                    WHERE workspace_id = ? AND status IN ('active', 'trialing')
                    LIMIT 1
                    """,
                    (workspace_id,),
                )
                if not existing_active_subscription:
                    now = utc_now_iso()
                    connection.execute(
                        """
                        INSERT INTO workspace_subscriptions (
                            id, workspace_id, plan_code, status, source, started_at, expires_at,
                            cancelled_at, metadata, created_at, updated_at
                        ) VALUES (?, ?, ?, 'active', 'legacy_migration', ?, NULL, NULL, CAST(? AS JSONB), ?, ?)
                        """,
                        (
                            str(uuid4()),
                            workspace_id,
                            target_plan_code,
                            now,
                            '{"legacy_migration": true}',
                            now,
                            now,
                        ),
                    )
                    activated_workspaces += 1

            for legacy_account in legacy_user_accounts:
                account_key = str(legacy_account["account_key"])
                existing_account = connection.fetchone(
                    """
                    SELECT id
                    FROM ml_accounts
                    WHERE workspace_id = ? AND (account_key = ? OR ml_user_id = ?)
                    LIMIT 1
                    """,
                    (
                        workspace_id,
                        account_key,
                        int(legacy_account["ml_user_id"]) if legacy_account["ml_user_id"] is not None else None,
                    ),
                )
                if existing_account:
                    continue

                now = utc_now_iso()
                connection.execute(
                    """
                    INSERT INTO ml_accounts (
                        id, workspace_id, linked_user_id, account_key, label, ml_user_id, nickname, site_id,
                        access_token_encrypted, refresh_token_encrypted, scope, source, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        workspace_id,
                        user_id,
                        account_key,
                        str(legacy_account["label"]),
                        int(legacy_account["ml_user_id"]) if legacy_account["ml_user_id"] is not None else None,
                        str(legacy_account["nickname"]) if legacy_account["nickname"] else None,
                        str(legacy_account["site_id"]) if legacy_account["site_id"] else None,
                        encrypt_secret(str(legacy_account["access_token"]), settings.encryption_key),
                        encrypt_secret(str(legacy_account["refresh_token"]), settings.encryption_key)
                        if legacy_account["refresh_token"]
                        else None,
                        str(legacy_account["scope"]) if legacy_account["scope"] else None,
                        str(legacy_account["source"] or "legacy_sqlite"),
                        str(legacy_account["created_at"] or now),
                        str(legacy_account["updated_at"] or now),
                    ),
                )
                migrated_accounts += 1

    print(f"Migrated new users: {migrated_users}")
    print(f"Migrated new ML accounts: {migrated_accounts}")
    print(f"Activated workspaces from legacy access: {activated_workspaces}")
    print("Legacy auth sessions were intentionally not migrated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
