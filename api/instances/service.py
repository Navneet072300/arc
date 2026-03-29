"""
Instance provisioning service: orchestrates DB records + Kubernetes resources.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import uuid

from kubernetes import client as k8s_client
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.backup import Backup
from api.db.models.instance import Instance
from api.db.models.read_replica import ReadReplica
from api.k8s import provisioner
from api.k8s.exceptions import K8sNotFoundError, K8sProvisioningError
from api.webhooks.service import dispatch_event

logger = logging.getLogger(__name__)

CPU_PRICE_PER_CORE_HOUR = 0.048
MEM_PRICE_PER_GB_HOUR = 0.006
STORAGE_PRICE_PER_GB_DAY = 0.0001


def _make_slug(user_id: uuid.UUID, name: str) -> str:
    uid_short = str(user_id).replace("-", "")[:8]
    safe_name = re.sub(r"[^a-z0-9\-]", "-", name.lower())[:20]
    return f"{uid_short}-{safe_name}"


def _connection_string(instance: Instance, password: str | None = None) -> str:
    if not instance.external_host:
        return ""
    pw_part = f":{password}" if password else ""
    return (
        f"postgresql://{instance.pg_username}{pw_part}"
        f"@{instance.external_host}:{instance.external_port}"
        f"/{instance.pg_db_name}"
    )


def _instance_payload(instance: Instance) -> dict:
    return {
        "instance_id": str(instance.id),
        "instance_name": instance.name,
        "slug": instance.slug,
        "status": instance.status,
        "pg_version": instance.pg_version,
        "external_host": instance.external_host,
        "external_port": instance.external_port,
    }


async def list_instances(db: AsyncSession, user_id: uuid.UUID) -> list[Instance]:
    result = await db.execute(
        select(Instance).where(Instance.user_id == user_id, Instance.status != "deleted")
    )
    return list(result.scalars())


async def get_instance(db: AsyncSession, user_id: uuid.UUID, instance_id: uuid.UUID) -> Instance | None:
    result = await db.execute(
        select(Instance).where(Instance.id == instance_id, Instance.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def create_instance(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    user_id: uuid.UUID,
    data: dict,
) -> tuple[Instance, str]:
    name = data["name"]
    slug = _make_slug(user_id, name)

    existing = await db.execute(select(Instance).where(Instance.slug == slug))
    if existing.scalar_one_or_none():
        slug = f"{slug}-{secrets.token_hex(2)}"

    namespace = f"pg-{slug}"
    statefulset_name = f"pg-{slug}"
    secret_name = f"pg-creds-{slug}"
    pg_username = data.get("pg_username", "pguser")

    instance = Instance(
        user_id=user_id,
        name=name,
        slug=slug,
        status="provisioning",
        k8s_namespace=namespace,
        k8s_statefulset=statefulset_name,
        k8s_secret_name=secret_name,
        pg_version=data.get("pg_version", "16"),
        cpu_request=data.get("cpu_request", "250m"),
        cpu_limit=data.get("cpu_limit", "500m"),
        mem_request=data.get("mem_request", "256Mi"),
        mem_limit=data.get("mem_limit", "512Mi"),
        storage_size=data.get("storage_size", "5Gi"),
        pg_db_name=data.get("pg_db_name", "postgres"),
        pg_username=pg_username,
        pool_mode=data.get("pool_mode", "transaction"),
        pool_size=data.get("pool_size", 20),
        max_client_conn=data.get("max_client_conn", 100),
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)

    await dispatch_event("instance.provisioning", _instance_payload(instance), user_id)

    password = secrets.token_hex(24)
    replication_password = secrets.token_hex(16)
    return instance, password, replication_password


async def run_provisioning(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
    password: str,
    replication_password: str = "",
) -> None:
    """Background task: provision K8s resources and update instance status."""
    try:
        await provisioner.provision_instance(api_client, instance, password, replication_password)

        for _ in range(36):
            await asyncio.sleep(5)
            if await provisioner.get_statefulset_ready(api_client, instance):
                break

        endpoint = await provisioner.get_service_endpoint(api_client, instance)
        if endpoint:
            instance.external_host, instance.external_port = endpoint

        instance.status = "running"
        await db.commit()
        await dispatch_event("instance.running", _instance_payload(instance), instance.user_id)

    except K8sProvisioningError as exc:
        logger.error("Provisioning failed for %s: %s", instance.slug, exc)
        instance.status = "error"
        await db.commit()
        await dispatch_event("instance.error", {**_instance_payload(instance), "error": str(exc)}, instance.user_id)


async def delete_instance(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
) -> None:
    instance.status = "deleting"
    await db.commit()
    try:
        await provisioner.deprovision_instance(api_client, instance)
    except K8sNotFoundError:
        pass
    except K8sProvisioningError as exc:
        logger.error("Deprovision error for %s: %s", instance.slug, exc)

    instance.status = "deleted"
    await db.commit()
    await dispatch_event("instance.deleted", _instance_payload(instance), instance.user_id)


async def suspend_instance(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
) -> None:
    """Manually suspend (scale to 0) a running instance."""
    from datetime import UTC, datetime

    await provisioner.scale_instance(api_client, instance, replicas=0)
    instance.status = "suspended"
    instance.suspended_at = datetime.now(tz=UTC)
    await db.commit()
    await db.refresh(instance)
    await dispatch_event(
        "instance.suspended",
        {**_instance_payload(instance), "suspended_at": instance.suspended_at.isoformat()},
        instance.user_id,
    )


async def resume_instance(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
) -> None:
    """Resume a suspended instance (scale back to 1 replica)."""
    await provisioner.scale_instance(api_client, instance, replicas=1)
    instance.status = "running"
    instance.suspended_at = None
    await db.commit()
    await db.refresh(instance)
    await dispatch_event("instance.running", _instance_payload(instance), instance.user_id)


async def rotate_credentials(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
) -> tuple[str, str]:
    new_password = secrets.token_hex(24)
    await provisioner.rotate_password(api_client, instance, new_password)
    conn_str = _connection_string(instance, new_password)
    await dispatch_event("credentials.rotated", _instance_payload(instance), instance.user_id)
    return new_password, conn_str


# ── Read Replicas ────────────────────────────────────────────────────────────

async def list_replicas(db: AsyncSession, instance: Instance) -> list[ReadReplica]:
    result = await db.execute(
        select(ReadReplica).where(
            ReadReplica.instance_id == instance.id,
            ReadReplica.status != "deleted",
        )
    )
    return list(result.scalars())


async def create_replica(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
) -> ReadReplica:
    """Create a DB record for a new read replica and kick off provisioning."""
    replica_index = len(await list_replicas(db, instance)) + 1
    replica_slug = f"{instance.slug}-r{replica_index}"

    replica = ReadReplica(
        instance_id=instance.id,
        slug=replica_slug,
        k8s_statefulset=f"pg-{replica_slug}",
        k8s_service=f"pg-{replica_slug}-external",
        status="provisioning",
    )
    db.add(replica)
    await db.commit()
    await db.refresh(replica)
    return replica


async def run_replica_provisioning(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
    replica: ReadReplica,
) -> None:
    """Background: deploy K8s resources for the replica, then update status."""
    try:
        await provisioner.provision_replica(api_client, instance, replica.slug)

        # Wait for StatefulSet to be ready (up to 3 min)
        for _ in range(36):
            await asyncio.sleep(5)
            if await provisioner.get_replica_ready(api_client, instance, replica.slug):
                break

        endpoint = await provisioner.get_replica_endpoint(api_client, instance, replica.slug)

        # Refresh replica from DB before updating
        result = await db.execute(select(ReadReplica).where(ReadReplica.id == replica.id))
        replica = result.scalar_one()
        if endpoint:
            replica.external_host, replica.external_port = endpoint
        replica.status = "running"
        await db.commit()

    except K8sProvisioningError as exc:
        logger.error("Replica provisioning failed for %s: %s", replica.slug, exc)
        result = await db.execute(select(ReadReplica).where(ReadReplica.id == replica.id))
        replica = result.scalar_one_or_none()
        if replica:
            replica.status = "error"
            await db.commit()


async def delete_replica(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
    replica: ReadReplica,
) -> None:
    replica.status = "deleting"
    await db.commit()
    try:
        await provisioner.deprovision_replica(api_client, instance, replica.slug)
    except Exception as exc:
        logger.error("Error deprovisioning replica %s: %s", replica.slug, exc)
    replica.status = "deleted"
    await db.commit()


# ── Backups / PITR ──────────────────────────────────────────────────────────

async def list_backups(db: AsyncSession, instance: Instance) -> list[Backup]:
    result = await db.execute(
        select(Backup).where(
            Backup.instance_id == instance.id,
            Backup.status != "deleted",
        ).order_by(Backup.created_at.desc())
    )
    return list(result.scalars())


async def create_backup(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
) -> Backup:
    from datetime import UTC, datetime
    import time as _time

    ts = int(_time.time())
    backup_slug = f"{instance.slug}-bk{ts}"

    backup = Backup(
        instance_id=instance.id,
        slug=backup_slug,
        status="creating",
        k8s_job=f"pg-backup-{backup_slug}",
        backup_pvc=f"pg-backup-{backup_slug}",
    )
    db.add(backup)
    await db.commit()
    await db.refresh(backup)

    await provisioner.create_backup(api_client, instance, backup_slug)
    return backup


async def run_backup_watcher(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
    backup: Backup,
) -> None:
    """Poll K8s Job until backup completes, then update status."""
    from datetime import UTC, datetime

    for _ in range(120):  # up to 10 min
        await asyncio.sleep(5)
        job_status = await provisioner.get_backup_job_status(api_client, instance, backup.slug)
        if job_status in ("succeeded", "failed"):
            result = await db.execute(select(Backup).where(Backup.id == backup.id))
            b = result.scalar_one_or_none()
            if b:
                b.status = "ready" if job_status == "succeeded" else "failed"
                b.completed_at = datetime.now(tz=UTC)
                await db.commit()
            return


async def delete_backup(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
    backup: Backup,
) -> None:
    backup.status = "deleted"
    await db.commit()
    try:
        await provisioner.delete_backup_resources(api_client, instance, backup.slug)
    except Exception as exc:
        logger.error("Error deleting backup resources %s: %s", backup.slug, exc)


async def restore_backup(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
    backup: Backup,
    recovery_target_time: str | None = None,
) -> Instance:
    """
    Create a new Instance record representing the restored fork, then
    spin up its K8s resources in the same namespace.
    """
    import time as _time

    ts = int(_time.time())
    restored_slug = f"{instance.slug}-rs{ts}"
    namespace = instance.k8s_namespace  # same namespace as primary
    sts_name = f"pg-{restored_slug}"

    restored = Instance(
        user_id=instance.user_id,
        name=f"{instance.name} (restored)",
        slug=restored_slug,
        status="restoring",
        k8s_namespace=namespace,
        k8s_statefulset=sts_name,
        k8s_secret_name=instance.k8s_secret_name,  # reuse same credentials
        pg_version=instance.pg_version,
        cpu_request=instance.cpu_request,
        cpu_limit=instance.cpu_limit,
        mem_request=instance.mem_request,
        mem_limit=instance.mem_limit,
        storage_size=instance.storage_size,
        pg_db_name=instance.pg_db_name,
        pg_username=instance.pg_username,
        pool_mode=instance.pool_mode,
        pool_size=instance.pool_size,
        max_client_conn=instance.max_client_conn,
        auto_suspend=False,
    )
    db.add(restored)
    await db.commit()
    await db.refresh(restored)

    await provisioner.restore_from_backup(
        api_client, instance, backup.slug, restored_slug, recovery_target_time
    )

    # Poll until ready, then update endpoint + status
    for _ in range(72):  # up to 6 min
        await asyncio.sleep(5)
        if await provisioner.get_statefulset_ready(api_client, restored):
            break

    endpoint = await provisioner.get_service_endpoint(api_client, restored)
    result = await db.execute(select(Instance).where(Instance.id == restored.id))
    restored = result.scalar_one()
    if endpoint:
        restored.external_host, restored.external_port = endpoint
    restored.status = "running"
    await db.commit()
    await db.refresh(restored)
    return restored
