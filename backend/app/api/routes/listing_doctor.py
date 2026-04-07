from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_listing_doctor_service, resolve_account
from app.schemas.listing_doctor import ListingDoctorJobAccepted, ListingDoctorJobRequest, ListingDoctorJobStatus
from app.services.listing_doctor import ListingDoctorService


router = APIRouter(prefix="/listing-doctor", tags=["listing-doctor"])


@router.post("/jobs", response_model=ListingDoctorJobAccepted)
async def create_listing_doctor_job(
    payload: ListingDoctorJobRequest,
    service: Annotated[ListingDoctorService, Depends(get_listing_doctor_service)],
    account_key: Annotated[str, Depends(resolve_account)],
) -> ListingDoctorJobAccepted:
    return await service.create_job(account_key=account_key, payload=payload)


@router.get("/jobs/{job_id}", response_model=ListingDoctorJobStatus)
async def get_listing_doctor_job(
    job_id: str,
    service: Annotated[ListingDoctorService, Depends(get_listing_doctor_service)],
) -> ListingDoctorJobStatus:
    return service.get_job(job_id)
