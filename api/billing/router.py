import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.billing.schemas import BillingSummaryResponse, UsagePoint, UsageResponse
from api.db.models.instance import Instance
from api.db.models.usage_record import BillingSummary, UsageRecord
from api.db.models.user import User
from api.db.session import get_db
from api.dependencies import get_current_user

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    instance_id: uuid.UUID = Query(...),
    start: date = Query(...),
    end: date = Query(...),
    granularity: str = Query("day", pattern="^(hour|day)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify ownership
    inst = await db.execute(
        select(Instance).where(Instance.id == instance_id, Instance.user_id == current_user.id)
    )
    if not inst.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Instance not found")

    trunc = "hour" if granularity == "hour" else "day"
    result = await db.execute(
        select(
            func.date_trunc(trunc, UsageRecord.recorded_at).label("period"),
            func.sum(UsageRecord.cpu_millicores * UsageRecord.interval_secs / 3_600_000).label("cpu_core_hours"),
            func.sum(
                UsageRecord.mem_bytes * UsageRecord.interval_secs / (1024**3 * 3600.0)
            ).label("mem_gb_hours"),
            func.sum(
                UsageRecord.storage_bytes * UsageRecord.interval_secs / (1024**3 * 86400.0)
            ).label("storage_gb_days"),
        )
        .where(
            UsageRecord.instance_id == instance_id,
            UsageRecord.recorded_at >= start,
            UsageRecord.recorded_at <= end,
        )
        .group_by("period")
        .order_by("period")
    )
    rows = result.all()
    data = [
        UsagePoint(
            period=str(row.period),
            cpu_core_hours=float(row.cpu_core_hours or 0),
            mem_gb_hours=float(row.mem_gb_hours or 0),
            storage_gb_days=float(row.storage_gb_days or 0),
        )
        for row in rows
    ]
    return UsageResponse(instance_id=instance_id, start=start, end=end, granularity=granularity, data=data)


@router.get("/summaries", response_model=list[BillingSummaryResponse])
async def list_summaries(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(BillingSummary)
        .where(BillingSummary.user_id == current_user.id)
        .order_by(BillingSummary.period_start.desc())
    )
    return list(result.scalars())


@router.get("/summaries/{summary_id}", response_model=BillingSummaryResponse)
async def get_summary(
    summary_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(BillingSummary).where(
            BillingSummary.id == summary_id, BillingSummary.user_id == current_user.id
        )
    )
    summary = result.scalar_one_or_none()
    if not summary:
        raise HTTPException(status_code=404, detail="Billing summary not found")
    return summary
