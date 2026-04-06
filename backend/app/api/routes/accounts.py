from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_accounts_service
from app.schemas.accounts import AccountsResponse
from app.services.accounts import AccountsService


router = APIRouter(tags=["accounts"])


@router.get("/accounts", response_model=AccountsResponse)
def list_accounts(
    service: Annotated[AccountsService, Depends(get_accounts_service)],
) -> AccountsResponse:
    return service.list_accounts()
