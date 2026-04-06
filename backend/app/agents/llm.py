from __future__ import annotations

from app.agents.config import AgentSettings


def build_chat_models(settings: AgentSettings) -> tuple[object, object]:
    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Missing AI dependencies. Install the updated backend requirements to enable the assistant.",
        ) from exc

    settings.validate_runtime()

    router_llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_router_model,
        temperature=settings.router_temperature,
        max_retries=2,
    )
    worker_llm = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.groq_model,
        temperature=settings.temperature,
        max_retries=2,
    )
    return router_llm, worker_llm
