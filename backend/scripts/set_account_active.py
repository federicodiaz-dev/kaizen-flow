from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "backend" / "data" / "kaizen_flow.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Activa o desactiva cuentas de Mercado Libre en la base SQLite de Kaizen Flow."
    )
    parser.add_argument(
        "identifier",
        help="Email, prefijo de email, account_key, label, nickname o ml_user_id de la cuenta.",
    )
    parser.add_argument(
        "--active",
        choices=("true", "false"),
        required=True,
        help="Nuevo valor para is_active.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"Ruta al archivo SQLite. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra qué cambiaría sin guardar.",
    )
    return parser.parse_args()


def normalize_bool(raw_value: str) -> int:
    return 1 if raw_value.strip().lower() == "true" else 0


def fetch_matching_rows(connection: sqlite3.Connection, identifier: str) -> list[sqlite3.Row]:
    normalized = identifier.strip().lower()
    return connection.execute(
        """
        SELECT
            ml_accounts.id,
            users.email,
            ml_accounts.account_key,
            ml_accounts.label,
            ml_accounts.nickname,
            ml_accounts.ml_user_id,
            ml_accounts.is_active
        FROM ml_accounts
        JOIN users ON users.id = ml_accounts.user_id
        WHERE
            lower(users.email) = ?
            OR lower(users.email) LIKE ?
            OR lower(ml_accounts.account_key) = ?
            OR lower(ml_accounts.label) = ?
            OR lower(COALESCE(ml_accounts.nickname, '')) = ?
            OR CAST(ml_accounts.ml_user_id AS TEXT) = ?
        ORDER BY users.email, ml_accounts.account_key
        """,
        (
            normalized,
            f"{normalized}@%",
            normalized,
            normalized,
            normalized,
            identifier.strip(),
        ),
    ).fetchall()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"No existe la base de datos: {db_path}")
        return 1

    next_value = normalize_bool(args.active)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = fetch_matching_rows(connection, args.identifier)
        if not rows:
            print(f"No encontré cuentas para '{args.identifier}'.")
            return 1

        print("Cuentas encontradas:")
        for row in rows:
            print(
                f"- id={row['id']} email={row['email']} "
                f"account_key={row['account_key']} label={row['label']} "
                f"nickname={row['nickname'] or '-'} ml_user_id={row['ml_user_id'] or '-'} "
                f"is_active={bool(row['is_active'])}"
            )

        if args.dry_run:
            print(f"\nDry run: se actualizarían {len(rows)} cuenta(s) a is_active={bool(next_value)}.")
            return 0

        account_ids = [int(row["id"]) for row in rows]
        placeholders = ", ".join("?" for _ in account_ids)
        connection.execute(
            f"UPDATE ml_accounts SET is_active = ? WHERE id IN ({placeholders})",
            [next_value, *account_ids],
        )
        connection.commit()

        print(f"\nActualizadas {len(account_ids)} cuenta(s) a is_active={bool(next_value)}.")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
