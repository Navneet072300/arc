import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.instance import Instance
from api.db.models.usage_record import BillingSummary
from api.db.models.user import User
from api.db.session import get_db
from api.dependencies import get_admin_user
from api.instances import service as instance_service
from api.k8s.client import get_k8s_client
from api.metering.collector import aggregate_billing

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    total_users = await db.scalar(select(func.count()).select_from(User))
    total_instances = await db.scalar(select(func.count()).select_from(Instance).where(Instance.status != "deleted"))
    running_instances = await db.scalar(select(func.count()).select_from(Instance).where(Instance.status == "running"))
    total_revenue = await db.scalar(select(func.coalesce(func.sum(BillingSummary.amount_usd), 0)))
    provisioning = await db.scalar(select(func.count()).select_from(Instance).where(Instance.status == "provisioning"))
    error_instances = await db.scalar(select(func.count()).select_from(Instance).where(Instance.status == "error"))

    return {
        "total_users": total_users or 0,
        "total_instances": total_instances or 0,
        "running_instances": running_instances or 0,
        "provisioning_instances": provisioning or 0,
        "error_instances": error_instances or 0,
        "total_revenue_usd": float(total_revenue or 0),
    }


@router.get("/users")
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()

    out = []
    for user in users:
        instance_count = await db.scalar(
            select(func.count()).select_from(Instance).where(
                Instance.user_id == user.id, Instance.status != "deleted"
            )
        )
        out.append({
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "instance_count": instance_count or 0,
            "created_at": user.created_at.isoformat(),
        })
    return out


@router.patch("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_admin_user),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_admin.id:
        raise HTTPException(status_code=400, detail="Cannot modify your own admin account")

    if "is_active" in body:
        user.is_active = bool(body["is_active"])
    if "is_admin" in body:
        user.is_admin = bool(body["is_admin"])

    await db.commit()
    return {"id": str(user.id), "is_active": user.is_active, "is_admin": user.is_admin}


@router.get("/instances")
async def list_all_instances(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    result = await db.execute(
        select(Instance, User.email)
        .join(User, Instance.user_id == User.id)
        .order_by(Instance.created_at.desc())
    )
    rows = result.all()
    return [
        {
            "id": str(i.id),
            "name": i.name,
            "slug": i.slug,
            "status": i.status,
            "pg_version": i.pg_version,
            "external_host": i.external_host,
            "external_port": i.external_port,
            "user_email": email,
            "user_id": str(i.user_id),
            "storage_size": i.storage_size,
            "cpu_request": i.cpu_request,
            "mem_request": i.mem_request,
            "created_at": i.created_at.isoformat(),
        }
        for i, email in rows
    ]


@router.delete("/instances/{instance_id}")
async def force_delete_instance(
    instance_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    result = await db.execute(select(Instance).where(Instance.id == instance_id))
    instance = result.scalar_one_or_none()
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")
    if instance.status in ("deleting", "deleted"):
        raise HTTPException(status_code=400, detail=f"Instance is already {instance.status}")

    api_client = get_k8s_client()
    background_tasks.add_task(instance_service.delete_instance, db, api_client, instance)
    return {"detail": "Deletion initiated", "id": str(instance_id)}


@router.post("/billing/run")
async def run_billing(
    background_tasks: BackgroundTasks,
    _: User = Depends(get_admin_user),
):
    background_tasks.add_task(aggregate_billing)
    return {"detail": "Billing aggregation started"}
