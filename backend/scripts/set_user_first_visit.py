from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT_DIR / "backend" / "data" / "kaizen_flow.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Actualiza el campo is_first_visit de un usuario en la base SQLite de Kaizen Flow."
    )
    parser.add_argument(
        "email",
        help="Email exacto del usuario.",
    )
    parser.add_argument(
        "--first-visit",
        choices=("true", "false"),
        required=True,
        help="Nuevo valor para is_first_visit.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"Ruta al archivo SQLite. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Muestra el cambio sin guardarlo.",
    )
    return parser.parse_args()


def normalize_bool(raw_value: str) -> int:
    return 1 if raw_value.strip().lower() == "true" else 0


def main() -> int:
    args = parse_args()
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        print(f"No existe la base de datos: {db_path}")
        return 1

    email = args.email.strip().lower()
    next_value = normalize_bool(args.first_visit)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT id, email, is_first_visit, created_at
            FROM users
            WHERE lower(email) = ?
            """,
            (email,),
        ).fetchone()

        if row is None:
            print(f"No encontré un usuario con email '{email}'.")
            return 1

        print("Usuario encontrado:")
        print(
            f"- id={row['id']} email={row['email']} "
            f"is_first_visit={bool(row['is_first_visit'])} created_at={row['created_at']}"
        )

        if args.dry_run:
            print(f"\nDry run: se actualizaría a is_first_visit={bool(next_value)}.")
            return 0

        connection.execute(
            "UPDATE users SET is_first_visit = ? WHERE id = ?",
            (next_value, int(row["id"])),
        )
        connection.commit()

        print(f"\nUsuario actualizado a is_first_visit={bool(next_value)}.")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    sys.exit(main())
