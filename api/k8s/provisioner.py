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

if TYPE_CHECKING:
    from api.db.models.instance import Instance

logger = logging.getLogger(__name__)


def _core(api_client: client.ApiClient) -> client.CoreV1Api:
    return client.CoreV1Api(api_client)


def _apps(api_client: client.ApiClient) -> client.AppsV1Api:
    return client.AppsV1Api(api_client)


async def provision_instance(api_client: client.ApiClient, instance: Instance, password: str) -> None:
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

        # 2. Secret
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_secret(
                namespace=instance.k8s_namespace,
                body=manifests.secret_manifest(instance, password),
            ),
        )
        logger.info("Created secret %s", instance.k8s_secret_name)

        # 3. PVC
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_persistent_volume_claim(
                namespace=instance.k8s_namespace,
                body=manifests.pvc_manifest(instance),
            ),
        )
        logger.info("Created PVC for %s", instance.slug)

        # 4. StatefulSet
        await loop.run_in_executor(
            None,
            lambda: apps.create_namespaced_stateful_set(
                namespace=instance.k8s_namespace,
                body=manifests.statefulset_manifest(instance),
            ),
        )
        logger.info("Created StatefulSet %s", instance.k8s_statefulset)

        # 5. ClusterIP service
        await loop.run_in_executor(
            None,
            lambda: core.create_namespaced_service(
                namespace=instance.k8s_namespace,
                body=manifests.clusterip_service_manifest(instance),
            ),
        )

        # 6. External service (NodePort / LoadBalancer)
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
    if spec.type == "NodePort":
        # For minikube, use the minikube IP
        node_port = spec.ports[0].node_port if spec.ports else None
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
        status = svc.status
        ingress = status.load_balancer.ingress if status and status.load_balancer else None
        if ingress:
            entry = ingress[0]
            host = entry.hostname or entry.ip
            port = spec.ports[0].port if spec.ports else 5432
            if host:
                return host, port
    return None


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
