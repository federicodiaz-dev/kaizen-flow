from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_auth_service, get_current_user
from app.schemas.auth import SessionResponse
from app.schemas.plans import PlanCatalogResponse, SelectPlanRequest
from app.services.auth import AuthService, AuthenticatedUser


router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=PlanCatalogResponse)
def list_plans(
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> PlanCatalogResponse:
    return PlanCatalogResponse(plans=service.list_public_plans())


@router.post("/select", response_model=SessionResponse)
def select_plan(
    payload: SelectPlanRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> SessionResponse:
    user = service.select_plan(
        user_id=current_user.id,
        plan_code=payload.plan_code,
    )
    return SessionResponse(user=user.to_profile())
