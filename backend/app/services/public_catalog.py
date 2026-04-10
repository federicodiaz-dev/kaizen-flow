from __future__ import annotations

import json
from typing import Any

from app.core.database import Database
from app.core.settings import Settings
from app.schemas.public import PublicPlan, PublicPlansResponse


class PublicCatalogService:
    def __init__(self, *, database: Database, settings: Settings) -> None:
        self._database = database
        self._settings = settings

    def list_public_plans(self) -> PublicPlansResponse:
        with self._database.connect() as connection:
            rows = connection.fetchall(
                """
                SELECT code, name, description, price_cents, currency, price_label, badge, is_recommended, entitlements
                FROM subscription_plans
                WHERE is_public = TRUE AND is_active = TRUE
                ORDER BY sort_order ASC, price_cents ASC
                """,
            )

        items = [self._row_to_plan(row) for row in rows]
        return PublicPlansResponse(app_url=self._settings.public_app_url, items=items)

    def _row_to_plan(self, row: dict[str, Any]) -> PublicPlan:
        entitlements = row.get("entitlements") or {}
        if isinstance(entitlements, str):
            try:
                entitlements = json.loads(entitlements)
            except json.JSONDecodeError:
                entitlements = {}
        features = entitlements.get("landing_features") if isinstance(entitlements, dict) else []
        if not isinstance(features, list):
            features = []
        return PublicPlan(
            code=str(row["code"]),
            name=str(row["name"]),
            description=str(row["description"]),
            price_cents=int(row["price_cents"]),
            currency=str(row["currency"]),
            price_label=str(row["price_label"]),
            badge=str(row["badge"]) if row.get("badge") else None,
            is_recommended=bool(row["is_recommended"]),
            features=[str(feature) for feature in features],
        )
