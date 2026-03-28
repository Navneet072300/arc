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

from api.db.models.instance import Instance
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
    )
    db.add(instance)
    await db.commit()
    await db.refresh(instance)

    await dispatch_event("instance.provisioning", _instance_payload(instance), user_id)

    password = secrets.token_hex(24)
    return instance, password


async def run_provisioning(
    db: AsyncSession,
    api_client: k8s_client.ApiClient,
    instance: Instance,
    password: str,
) -> None:
    """Background task: provision K8s resources and update instance status."""
    try:
        await provisioner.provision_instance(api_client, instance, password)

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
