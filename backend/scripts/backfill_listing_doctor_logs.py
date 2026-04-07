from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.listing_doctor import ListingDoctorJobStore


def _iter_user_ids(base_dir: Path, user_id: int | None) -> list[int]:
    if user_id is not None:
        return [user_id]

    user_ids: list[int] = []
    for path in base_dir.glob("user_*"):
        if not path.is_dir():
            continue
        suffix = path.name.removeprefix("user_")
        if suffix.isdigit():
            user_ids.append(int(suffix))
    return sorted(user_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill Listing Doctor execution logs.")
    parser.add_argument("--user-id", type=int, default=None, help="Specific user id to backfill.")
    args = parser.parse_args()

    base_dir = ROOT_DIR / "data" / "listing_doctor"
    if not base_dir.exists():
        print(f"No Listing Doctor directory found at {base_dir}")
        return 0

    total_jobs = 0
    touched_users = 0
    for user_id in _iter_user_ids(base_dir, args.user_id):
        store = ListingDoctorJobStore(base_dir, user_id=user_id)
        job_paths = sorted(store._jobs_dir.glob("*.json"))
        for job_path in job_paths:
            store.ensure_terminal_log(job_path.stem)
            total_jobs += 1
        touched_users += 1
        print(
            {
                "user_id": user_id,
                "jobs_backfilled": len(job_paths),
                "logs_dir": str(store._logs_dir),
            }
        )

    print({"users_processed": touched_users, "total_jobs_backfilled": total_jobs})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
