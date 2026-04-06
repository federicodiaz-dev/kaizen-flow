from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_accounts_service
from app.schemas.accounts import AccountsResponse, DefaultAccountResponse
from app.schemas.auth import DefaultAccountRequest
from app.services.accounts import AccountsService


router = APIRouter(tags=["accounts"])


@router.get("/accounts", response_model=AccountsResponse)
def list_accounts(
    service: Annotated[AccountsService, Depends(get_accounts_service)],
) -> AccountsResponse:
    return service.list_accounts()


@router.patch("/accounts/default", response_model=DefaultAccountResponse)
def set_default_account(
    payload: DefaultAccountRequest,
    service: Annotated[AccountsService, Depends(get_accounts_service)],
) -> DefaultAccountResponse:
    return service.set_default_account(payload.account_key)
