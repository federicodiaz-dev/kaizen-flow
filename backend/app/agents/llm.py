from __future__ import annotations

from app.agents.config import AgentSettings
from app.core.ai_usage_reporting import create_chat_model


def build_chat_models(settings: AgentSettings) -> tuple[object, object]:
    settings.validate_runtime()

    router_llm = create_chat_model(
        settings,
        model=settings.google_router_model,
        temperature=settings.router_temperature,
        feature="agents.router",
        max_retries=2,
    )
    worker_llm = create_chat_model(
        settings,
        model=settings.google_model,
        temperature=settings.temperature,
        feature="agents.worker",
        max_retries=2,
    )
    return router_llm, worker_llm
