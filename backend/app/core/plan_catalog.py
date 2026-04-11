from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlanDefinition:
    code: str
    name: str
    headline: str
    description: str
    price_monthly: int
    currency: str
    max_accounts: int
    reply_assistant_limit: int | None
    listing_doctor_limit: int | None
    features: tuple[str, ...]
    sort_order: int


DEFAULT_PLAN_CATALOG: tuple[PlanDefinition, ...] = (
    PlanDefinition(
        code="starter",
        name="Starter",
        headline="Control operativo base para sellers que arrancan",
        description=(
            "Centraliza preguntas, reclamos y alertas basicas con una base lista "
            "para profesionalizar la operacion."
        ),
        price_monthly=29,
        currency="USD",
        max_accounts=1,
        reply_assistant_limit=200,
        listing_doctor_limit=5,
        features=(
            "Panel unificado",
            "Gestion de preguntas y reclamos",
            "Alertas basicas",
            "Reply Assistant hasta 200 mensajes",
            "Listing Doctor hasta 5 analisis",
        ),
        sort_order=10,
    ),
    PlanDefinition(
        code="growth",
        name="Growth",
        headline="El plan recomendado para sellers en expansion",
        description=(
            "Activa automatizacion, benchmark competitivo profundo y asistentes IA "
            "sin limites para escalar con criterio."
        ),
        price_monthly=79,
        currency="USD",
        max_accounts=1,
        reply_assistant_limit=None,
        listing_doctor_limit=None,
        features=(
            "Todo Starter",
            "Listing Doctor ilimitado",
            "Benchmark competitivo profundo",
            "Copywriter con contexto de mercado",
            "Quick wins priorizados por IA",
        ),
        sort_order=20,
    ),
    PlanDefinition(
        code="scale",
        name="Scale",
        headline="Operacion avanzada para agencias, marcas y multi cuenta",
        description=(
            "Amplia la capacidad operativa con multi cuenta, reportes avanzados y "
            "soporte prioritario para equipos intensivos."
        ),
        price_monthly=149,
        currency="USD",
        max_accounts=5,
        reply_assistant_limit=None,
        listing_doctor_limit=None,
        features=(
            "Todo Growth",
            "Hasta 5 cuentas Mercado Libre",
            "Reportes avanzados",
            "Exportaciones e informes",
            "Soporte prioritario",
        ),
        sort_order=30,
    ),
)


DEFAULT_PLAN_BY_CODE = {plan.code: plan for plan in DEFAULT_PLAN_CATALOG}
DEFAULT_PLAN_CODE = DEFAULT_PLAN_CATALOG[0].code
