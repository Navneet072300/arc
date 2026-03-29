"""
High-level orchestration: provision and deprovision PostgreSQL instances in Kubernetes.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from kubernetes import client
from kubernetes.client.rest import ApiException

from api.k8s import manifests
from api.k8s.exceptions import K8sNotFoundError, K8sProvisioningError
from api.k8s.manifests import PGBOUNCER_PORT

if TYPE_CHECKING:
    from api.db.models.instance import Instance

logger = logging.getLogger(__name__)


def _core(api_client: client.ApiClient) -> client.CoreV1Api:
    return client.CoreV1Api(api_client)


def _apps(api_client: client.ApiClient) -> client.AppsV1Api:
    return client.AppsV1Api(api_client)


async def provision_instance(
    api_client: client.ApiClient,
    instance: Instance,
    password: str,
    replication_password: str = "",
) -> None:
    """Create all K8s resources for a new instance. Raises K8sProvisioningError on failure."""
    loop = asyncio.get_event_loop()
    core = _core(api_client)
    apps = _apps(api_client)

    try:
        # 1. Namespace
        await loop.run_in_executor(
            None,
            lambda: core.create_namespace(body=manifests.namespace_manifest(instance)),
        )
        logger.info("Created namespace %s", instance.k8s_namespace)

        # 2. Secret (includes replication password)
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_secret(
                namespace=instance.k8s_namespace,
                body=manifests.secret_manifest(instance, password, replication_password),
            ),
        )
        logger.info("Created secret %s", instance.k8s_secret_name)

        # 3. ConfigMap with initdb replication script
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_config_map(
                namespace=instance.k8s_namespace,
                body=manifests.replication_config_manifest(instance),
            ),
        )
        logger.info("Created replication ConfigMap for %s", instance.slug)

        # 4. WAL archive PVC (for PITR)
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_persistent_volume_claim(
                namespace=instance.k8s_namespace,
                body=manifests.wal_archive_pvc_manifest(instance),
            ),
        )
        logger.info("Created WAL archive PVC for %s", instance.slug)

        # 5. PVC
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_persistent_volume_claim(
                namespace=instance.k8s_namespace,
                body=manifests.pvc_manifest(instance),
            ),
        )
        logger.info("Created PVC for %s", instance.slug)

        # 5. StatefulSet
        await loop.run_in_executor(
            None,
            lambda: apps.create_namespaced_stateful_set(
                namespace=instance.k8s_namespace,
                body=manifests.statefulset_manifest(instance),
            ),
        )
        logger.info("Created StatefulSet %s", instance.k8s_statefulset)

        # 6. ClusterIP service
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_service(
                namespace=instance.k8s_namespace,
                body=manifests.clusterip_service_manifest(instance),
            ),
        )

        # 7. External service (NodePort / LoadBalancer)
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_service(
                namespace=instance.k8s_namespace,
                body=manifests.external_service_manifest(instance),
            ),
        )
        logger.info("Created services for %s", instance.slug)

    except ApiException as exc:
        logger.error("K8s API error provisioning %s: %s", instance.slug, exc)
        # Best-effort cleanup — delete the namespace which cascades everything
        try:
            await deprovision_instance(api_client, instance)
        except Exception:
            pass
        raise K8sProvisioningError(str(exc)) from exc


async def provision_replica(
    api_client: client.ApiClient,
    instance: Instance,
    replica_slug: str,
) -> None:
    """Create K8s resources for a read replica in the primary's namespace."""
    loop = asyncio.get_event_loop()
    core = _core(api_client)
    apps = _apps(api_client)

    try:
        # PVC for replica data
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_persistent_volume_claim(
                namespace=instance.k8s_namespace,
                body=manifests.replica_pvc_manifest(instance, replica_slug),
            ),
        )
        logger.info("Created replica PVC for %s", replica_slug)

        # Replica StatefulSet (with pg_basebackup init container)
        await loop.run_in_executor(
            None,
            lambda: apps.create_namespaced_stateful_set(
                namespace=instance.k8s_namespace,
                body=manifests.replica_statefulset_manifest(instance, replica_slug),
            ),
        )
        logger.info("Created replica StatefulSet pg-%s", replica_slug)

        # External service for replica
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_service(
                namespace=instance.k8s_namespace,
                body=manifests.replica_service_manifest(instance, replica_slug),
            ),
        )
        logger.info("Created replica service for %s", replica_slug)

    except ApiException as exc:
        logger.error("K8s API error provisioning replica %s: %s", replica_slug, exc)
        await deprovision_replica(api_client, instance, replica_slug)
        raise K8sProvisioningError(str(exc)) from exc


async def deprovision_replica(
    api_client: client.ApiClient,
    instance: Instance,
    replica_slug: str,
) -> None:
    """Delete replica resources (StatefulSet + PVC + Service)."""
    loop = asyncio.get_event_loop()
    core = _core(api_client)
    apps = _apps(api_client)

    for coro in [
        lambda: apps.delete_namespaced_stateful_set(
            name=f"pg-{replica_slug}", namespace=instance.k8s_namespace
        ),
        lambda: core.delete_namespaced_service(
            name=f"pg-{replica_slug}-external", namespace=instance.k8s_namespace
        ),
        lambda: core.delete_namespaced_persistent_volume_claim(
            name=f"pg-data-{replica_slug}", namespace=instance.k8s_namespace
        ),
    ]:
        try:
            await loop.run_in_executor(None, coro)
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("Error deprovisioning replica resource: %s", exc)


async def get_replica_endpoint(
    api_client: client.ApiClient,
    instance: Instance,
    replica_slug: str,
) -> tuple[str, int] | None:
    """Return (host, port) for the replica external service, or None if not ready."""
    loop = asyncio.get_event_loop()
    core = _core(api_client)
    svc_name = f"pg-{replica_slug}-external"
    try:
        svc = await loop.run_in_executor(
            None,
            lambda: core.read_namespaced_service(name=svc_name, namespace=instance.k8s_namespace),
        )
    except ApiException:
        return None

    spec = svc.spec
    pgb_port_entry = next((p for p in (spec.ports or []) if p.port == PGBOUNCER_PORT), None)
    port_entry = pgb_port_entry or (spec.ports[0] if spec.ports else None)
    if not port_entry:
        return None

    if spec.type == "NodePort":
        node_port = port_entry.node_port
        if not node_port:
            return None
        try:
            import subprocess
            result = subprocess.run(["minikube", "ip"], capture_output=True, text=True, timeout=5)
            host = result.stdout.strip() if result.returncode == 0 else "localhost"
        except Exception:
            host = "localhost"
        return host, node_port

    elif spec.type == "LoadBalancer":
        ingress = svc.status.load_balancer.ingress if svc.status and svc.status.load_balancer else None
        if ingress:
            entry = ingress[0]
            host = entry.hostname or entry.ip
            if host:
                return host, port_entry.port
    return None


async def get_replica_ready(
    api_client: client.ApiClient,
    instance: Instance,
    replica_slug: str,
) -> bool:
    loop = asyncio.get_event_loop()
    apps = _apps(api_client)
    try:
        sts = await loop.run_in_executor(
            None,
            lambda: apps.read_namespaced_stateful_set(
                name=f"pg-{replica_slug}",
                namespace=instance.k8s_namespace,
            ),
        )
        return (sts.status.ready_replicas or 0) >= 1
    except ApiException:
        return False


# ── PITR: Backup & Restore ───────────────────────────────────────────────────

async def create_backup(
    api_client: client.ApiClient,
    instance: Instance,
    backup_slug: str,
) -> None:
    """Create backup PVC and trigger a pg_basebackup Job."""
    loop = asyncio.get_event_loop()
    core = _core(api_client)
    batch = client.BatchV1Api(api_client)

    try:
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_persistent_volume_claim(
                namespace=instance.k8s_namespace,
                body=manifests.backup_pvc_manifest(instance, backup_slug),
            ),
        )
        await loop.run_in_executor(
            None,
            lambda: batch.create_namespaced_job(
                namespace=instance.k8s_namespace,
                body=manifests.backup_job_manifest(instance, backup_slug),
            ),
        )
        logger.info("Created backup job for %s → %s", instance.slug, backup_slug)
    except ApiException as exc:
        raise K8sProvisioningError(str(exc)) from exc


async def get_backup_job_status(
    api_client: client.ApiClient,
    instance: Instance,
    backup_slug: str,
) -> str:
    """Return 'succeeded' | 'failed' | 'running'."""
    loop = asyncio.get_event_loop()
    batch = client.BatchV1Api(api_client)
    try:
        job = await loop.run_in_executor(
            None,
            lambda: batch.read_namespaced_job(
                name=f"pg-backup-{backup_slug}",
                namespace=instance.k8s_namespace,
            ),
        )
        if job.status.succeeded and job.status.succeeded >= 1:
            return "succeeded"
        if job.status.failed and job.status.failed >= job.spec.backoff_limit + 1:
            return "failed"
        return "running"
    except ApiException:
        return "failed"


async def delete_backup_resources(
    api_client: client.ApiClient,
    instance: Instance,
    backup_slug: str,
) -> None:
    """Delete backup Job + PVC."""
    loop = asyncio.get_event_loop()
    core = _core(api_client)
    batch = client.BatchV1Api(api_client)
    for coro in [
        lambda: batch.delete_namespaced_job(
            name=f"pg-backup-{backup_slug}",
            namespace=instance.k8s_namespace,
            body=client.V1DeleteOptions(propagation_policy="Foreground"),
        ),
        lambda: core.delete_namespaced_persistent_volume_claim(
            name=f"pg-backup-{backup_slug}",
            namespace=instance.k8s_namespace,
        ),
    ]:
        try:
            await loop.run_in_executor(None, coro)
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("Error deleting backup resource %s: %s", backup_slug, exc)


async def restore_from_backup(
    api_client: client.ApiClient,
    instance: Instance,
    backup_slug: str,
    restored_slug: str,
    recovery_target_time: str | None = None,
) -> None:
    """
    Create a restored instance StatefulSet + services in the same namespace.
    Uses backup PVC data + WAL archive for point-in-time recovery.
    """
    loop = asyncio.get_event_loop()
    core = _core(api_client)
    apps = _apps(api_client)

    try:
        # New data PVC for the restored instance
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_persistent_volume_claim(
                namespace=instance.k8s_namespace,
                body=manifests.pvc_manifest_for_slug(instance, restored_slug),
            ),
        )

        # Restored StatefulSet (init container copies backup → data PVC)
        await loop.run_in_executor(
            None,
            lambda: apps.create_namespaced_stateful_set(
                namespace=instance.k8s_namespace,
                body=manifests.restore_statefulset_manifest(
                    instance, backup_slug, restored_slug, recovery_target_time
                ),
            ),
        )

        # External service for restored instance
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_service(
                namespace=instance.k8s_namespace,
                body=manifests.replica_service_manifest(instance, restored_slug),
            ),
        )
        logger.info("Triggered restore %s from backup %s (target_time=%s)",
                    restored_slug, backup_slug, recovery_target_time)
    except ApiException as exc:
        raise K8sProvisioningError(str(exc)) from exc


async def deprovision_instance(api_client: client.ApiClient, instance: Instance) -> None:
    """Delete the namespace — K8s cascades all child resources."""
    loop = asyncio.get_event_loop()
    core = _core(api_client)
    try:
        await loop.run_in_executor(
            None,
            lambda: core.delete_namespace(name=instance.k8s_namespace),
        )
        logger.info("Deleted namespace %s", instance.k8s_namespace)
    except ApiException as exc:
        if exc.status == 404:
            raise K8sNotFoundError(instance.k8s_namespace) from exc
        raise K8sProvisioningError(str(exc)) from exc


async def get_statefulset_ready(api_client: client.ApiClient, instance: Instance) -> bool:
    loop = asyncio.get_event_loop()
    apps = _apps(api_client)
    try:
        sts = await loop.run_in_executor(
            None,
            lambda: apps.read_namespaced_stateful_set(
                name=instance.k8s_statefulset,
                namespace=instance.k8s_namespace,
            ),
        )
        return (sts.status.ready_replicas or 0) >= 1
    except ApiException:
        return False


async def get_service_endpoint(api_client: client.ApiClient, instance: Instance) -> tuple[str, int] | None:
    """Return (host, port) for the external service, or None if not yet available."""
    loop = asyncio.get_event_loop()
    core = _core(api_client)
    svc_name = f"pg-{instance.slug}-external"
    try:
        svc = await loop.run_in_executor(
            None,
            lambda: core.read_namespaced_service(name=svc_name, namespace=instance.k8s_namespace),
        )
    except ApiException:
        return None

    spec = svc.spec
    # Find the pgbouncer port entry (port 6432); fall back to first port
    pgb_port_entry = next((p for p in (spec.ports or []) if p.port == PGBOUNCER_PORT), None)
    port_entry = pgb_port_entry or (spec.ports[0] if spec.ports else None)
    if not port_entry:
        return None

    if spec.type == "NodePort":
        node_port = port_entry.node_port
        if not node_port:
            return None
        try:
            import subprocess
            result = subprocess.run(["minikube", "ip"], capture_output=True, text=True, timeout=5)
            host = result.stdout.strip() if result.returncode == 0 else "localhost"
        except Exception:
            host = "localhost"
        return host, node_port

    elif spec.type == "LoadBalancer":
        ingress = svc.status.load_balancer.ingress if svc.status and svc.status.load_balancer else None
        if ingress:
            entry = ingress[0]
            host = entry.hostname or entry.ip
            if host:
                return host, port_entry.port
    return None


async def scale_instance(api_client: client.ApiClient, instance: Instance, replicas: int) -> None:
    """Scale the StatefulSet to the given number of replicas (0 = suspended, 1 = running)."""
    loop = asyncio.get_event_loop()
    apps = _apps(api_client)
    try:
        await loop.run_in_executor(
            None,
            lambda: apps.patch_namespaced_stateful_set(
                name=instance.k8s_statefulset,
                namespace=instance.k8s_namespace,
                body={"spec": {"replicas": replicas}},
            ),
        )
        logger.info("Scaled %s to %d replicas", instance.slug, replicas)
    except ApiException as exc:
        raise K8sProvisioningError(str(exc)) from exc


async def rotate_password(api_client: client.ApiClient, instance: Instance, new_password: str) -> None:
    """Patch the K8s Secret with a new password and trigger a StatefulSet rollout."""
    import base64
    import time

    loop = asyncio.get_event_loop()
    core = _core(api_client)
    apps = _apps(api_client)

    encoded = base64.b64encode(new_password.encode()).decode()
    patch_secret = {"data": {"POSTGRES_PASSWORD": encoded}}
    await loop.run_in_executor(
        None,
        lambda: core.patch_namespaced_secret(
            name=instance.k8s_secret_name,
            namespace=instance.k8s_namespace,
            body=patch_secret,
        ),
    )

    # Trigger rollout by patching an annotation on the pod template
    patch_sts = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {"kubectl.kubernetes.io/restartedAt": str(time.time())}
                }
            }
        }
    }
    await loop.run_in_executor(
        None,
        lambda: apps.patch_namespaced_stateful_set(
            name=instance.k8s_statefulset,
            namespace=instance.k8s_namespace,
            body=patch_sts,
        ),
    )
