import uuid
from datetime import date, datetime

from pydantic import BaseModel


class UsagePoint(BaseModel):
    period: str
    cpu_core_hours: float
    mem_gb_hours: float
    storage_gb_days: float


class UsageResponse(BaseModel):
    instance_id: uuid.UUID
    start: date
    end: date
    granularity: str
    data: list[UsagePoint]


class BillingSummaryResponse(BaseModel):
    id: uuid.UUID
    instance_id: uuid.UUID
    period_start: date
    period_end: date
    cpu_core_hours: float | None
    mem_gb_hours: float | None
    storage_gb_days: float | None
    amount_usd: float | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
