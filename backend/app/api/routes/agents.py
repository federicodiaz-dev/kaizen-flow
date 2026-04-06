from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.agents.service import BusinessAssistantService
from app.api.dependencies import get_agents_service, resolve_account
from app.schemas.agents import (
    AgentMessageRequest,
    AgentMessageResponse,
    AgentThreadDetail,
    AgentThreadSummary,
    AgentsHealthResponse,
)


router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/health", response_model=AgentsHealthResponse)
async def health(
    service: Annotated[BusinessAssistantService, Depends(get_agents_service)],
) -> AgentsHealthResponse:
    return AgentsHealthResponse(**service.health())


@router.get("/threads", response_model=list[AgentThreadSummary])
async def list_threads(
    service: Annotated[BusinessAssistantService, Depends(get_agents_service)],
) -> list[AgentThreadSummary]:
    return [AgentThreadSummary(**thread) for thread in service.list_threads()]


@router.post("/threads", response_model=AgentThreadDetail)
async def create_thread(
    service: Annotated[BusinessAssistantService, Depends(get_agents_service)],
) -> AgentThreadDetail:
    return AgentThreadDetail(**service.create_thread())


@router.get("/threads/{thread_id}", response_model=AgentThreadDetail)
async def get_thread(
    thread_id: str,
    service: Annotated[BusinessAssistantService, Depends(get_agents_service)],
) -> AgentThreadDetail:
    return AgentThreadDetail(**service.get_thread(thread_id))


@router.post("/threads/{thread_id}/messages", response_model=AgentMessageResponse)
async def send_message(
    thread_id: str,
    payload: AgentMessageRequest,
    service: Annotated[BusinessAssistantService, Depends(get_agents_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> AgentMessageResponse:
    response = await service.send_message(
        thread_id=thread_id,
        user_input=payload.content,
        account_key=account_key,
        site_id=payload.site_id,
    )
    return AgentMessageResponse(**response)
