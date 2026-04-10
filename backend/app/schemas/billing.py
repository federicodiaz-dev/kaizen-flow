from __future__ import annotations

from pydantic import BaseModel, Field

from .auth import SessionResponse


class SimulatedCheckoutRequest(BaseModel):
    plan_code: str = Field(..., min_length=1, max_length=50)


class CheckoutSimulationResponse(SessionResponse):
    pass
