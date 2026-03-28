"""
Background metering collector: polls k8s metrics-server every N seconds,
writes UsageRecord rows, and aggregates daily BillingSummary rows.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.config import settings
from api.db.models.instance import Instance
from api.db.models.usage_record import BillingSummary, UsageRecord
from api.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Pricing (USD)
CPU_PRICE_PER_CORE_HOUR = 0.048
MEM_PRICE_PER_GB_HOUR = 0.006
STORAGE_PRICE_PER_GB_DAY = 0.0001


async def collect_usage() -> None:
    """Poll k8s metrics-server for all running instances and write UsageRecord rows."""
    from kubernetes import client as k8s
    from kubernetes.client.rest import ApiException

    from api.k8s.client import get_k8s_client

    api_client = get_k8s_client()
    metrics_api = k8s.CustomObjectsApi(api_client)
    loop = asyncio.get_event_loop()

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Instance).where(Instance.status == "running"))
        instances = list(result.scalars())

    for instance in instances:
        try:
            pod_metrics = await loop.run_in_executor(
                None,
                lambda ns=instance.k8s_namespace: metrics_api.list_namespaced_custom_object(
                    group="metrics.k8s.io",
                    version="v1beta1",
                    namespace=ns,
                    plural="pods",
                ),
            )
            total_cpu = 0.0
            total_mem = 0
            for pod in pod_metrics.get("items", []):
                for container in pod.get("containers", []):
                    usage = container.get("usage", {})
                    cpu_str = usage.get("cpu", "0")
                    mem_str = usage.get("memory", "0")
                    total_cpu += _parse_cpu(cpu_str)
                    total_mem += _parse_memory(mem_str)

            # PVC storage — use configured size as capacity
            storage_bytes = _parse_storage(instance.storage_size)

            async with AsyncSessionLocal() as db:
                db.add(
                    UsageRecord(
                        instance_id=instance.id,
                        cpu_millicores=total_cpu,
                        mem_bytes=total_mem,
                        storage_bytes=storage_bytes,
                        interval_secs=settings.METERING_INTERVAL_SECS,
                    )
                )
                await db.commit()

        except ApiException as exc:
            if exc.status == 404:
                logger.debug("No metrics yet for %s (pod not ready)", instance.slug)
            else:
                logger.warning("Metrics error for %s: %s", instance.slug, exc)
        except Exception as exc:
            logger.warning("Unexpected metering error for %s: %s", instance.slug, exc)


async def aggregate_billing() -> None:
    """Aggregate yesterday's usage into BillingSummary rows (upsert)."""
    yesterday = date.today() - timedelta(days=1)
    period_start = yesterday
    period_end = yesterday

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Instance).where(Instance.status.in_(["running", "deleted", "error"])))
        instances = list(result.scalars())

    for instance in instances:
        async with AsyncSessionLocal() as db:
            from sqlalchemy import func

            agg = await db.execute(
                select(
                    func.sum(UsageRecord.cpu_millicores * UsageRecord.interval_secs / 3_600_000).label("cpu_core_hours"),
                    func.sum(
                        UsageRecord.mem_bytes * UsageRecord.interval_secs / (1024**3 * 3600.0)
                    ).label("mem_gb_hours"),
                    func.sum(
                        UsageRecord.storage_bytes * UsageRecord.interval_secs / (1024**3 * 86400.0)
                    ).label("storage_gb_days"),
                ).where(
                    UsageRecord.instance_id == instance.id,
                    func.date(UsageRecord.recorded_at) == yesterday,
                )
            )
            row = agg.one()
            cpu_h = float(row.cpu_core_hours or 0)
            mem_h = float(row.mem_gb_hours or 0)
            stor_d = float(row.storage_gb_days or 0)
            amount = (
                cpu_h * CPU_PRICE_PER_CORE_HOUR
                + mem_h * MEM_PRICE_PER_GB_HOUR
                + stor_d * STORAGE_PRICE_PER_GB_DAY
            )

            stmt = (
                pg_insert(BillingSummary)
                .values(
                    user_id=instance.user_id,
                    instance_id=instance.id,
                    period_start=period_start,
                    period_end=period_end,
                    cpu_core_hours=cpu_h,
                    mem_gb_hours=mem_h,
                    storage_gb_days=stor_d,
                    amount_usd=round(amount, 6),
                    status="draft",
                )
                .on_conflict_do_update(
                    index_elements=["instance_id", "period_start"],
                    set_={
                        "cpu_core_hours": cpu_h,
                        "mem_gb_hours": mem_h,
                        "storage_gb_days": stor_d,
                        "amount_usd": round(amount, 6),
                    },
                )
            )
            await db.execute(stmt)
            await db.commit()
            logger.info("Billing summary updated for instance %s on %s", instance.slug, yesterday)


async def check_idle_instances() -> None:
    """Suspend running instances that have been idle longer than their idle_timeout_minutes."""
    if not settings.SCALE_TO_ZERO_ENABLED:
        return

    from datetime import timezone

    from sqlalchemy import func

    from api.db.models.usage_record import UsageRecord
    from api.k8s.client import get_k8s_client
    from api.k8s.provisioner import scale_instance

    now = datetime.now(tz=timezone.utc)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Instance).where(
                Instance.status == "running",
                Instance.auto_suspend.is_(True),
            )
        )
        instances = list(result.scalars())

    api_client = get_k8s_client()

    for instance in instances:
        idle_threshold = timedelta(minutes=instance.idle_timeout_minutes)
        window_start = now - idle_threshold

        async with AsyncSessionLocal() as db:
            agg = await db.execute(
                select(func.max(UsageRecord.cpu_millicores)).where(
                    UsageRecord.instance_id == instance.id,
                    UsageRecord.recorded_at >= window_start,
                )
            )
            max_cpu = agg.scalar() or 0.0

        # Instance is idle if max CPU in the window is near zero
        if max_cpu < 1.0:  # < 1 millicores
            logger.info(
                "Instance %s idle for >%d min (max_cpu=%.2fm) — suspending",
                instance.slug,
                instance.idle_timeout_minutes,
                max_cpu,
            )
            try:
                await scale_instance(api_client, instance, replicas=0)
                async with AsyncSessionLocal() as db:
                    inst = await db.get(Instance, instance.id)
                    if inst:
                        inst.status = "suspended"
                        inst.suspended_at = now
                        await db.commit()
                from api.webhooks.service import dispatch_event
                await dispatch_event(
                    "instance.suspended",
                    {
                        "instance_id": str(instance.id),
                        "slug": instance.slug,
                        "suspended_at": now.isoformat(),
                    },
                    instance.user_id,
                )
            except Exception as exc:
                logger.error("Failed to suspend %s: %s", instance.slug, exc)


def _parse_cpu(cpu_str: str) -> float:
    """Parse k8s CPU string to millicores. e.g. '250m' -> 250.0, '0.5' -> 500.0"""
    if cpu_str.endswith("n"):
        return float(cpu_str[:-1]) / 1_000_000
    if cpu_str.endswith("u"):
        return float(cpu_str[:-1]) / 1_000
    if cpu_str.endswith("m"):
        return float(cpu_str[:-1])
    return float(cpu_str) * 1000


def _parse_memory(mem_str: str) -> int:
    """Parse k8s memory string to bytes. e.g. '256Mi' -> 268435456"""
    units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4, "K": 1000, "M": 1000**2, "G": 1000**3}
    for suffix, mult in units.items():
        if mem_str.endswith(suffix):
            return int(float(mem_str[: -len(suffix)]) * mult)
    return int(mem_str)


def _parse_storage(storage_str: str) -> int:
    return _parse_memory(storage_str)
