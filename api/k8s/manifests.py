"""
Pure Python functions returning Kubernetes manifest dicts.
No cluster access — trivially unit-testable.
"""
from __future__ import annotations

import base64
from typing import TYPE_CHECKING

from api.config import settings

if TYPE_CHECKING:
    from api.db.models.instance import Instance

PGBOUNCER_PORT = 6432


def namespace_manifest(instance: Instance) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "Namespace",
        "metadata": {
            "name": instance.k8s_namespace,
            "labels": {
                "managed-by": "serverless-pg",
                "user-id": str(instance.user_id),
                "instance-id": str(instance.id),
            },
        },
    }


def secret_manifest(instance: Instance, password: str) -> dict:
    def b64(s: str) -> str:
        return base64.b64encode(s.encode()).decode()

    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": instance.k8s_secret_name,
            "namespace": instance.k8s_namespace,
        },
        "type": "Opaque",
        "data": {
            "POSTGRES_PASSWORD": b64(password),
            "POSTGRES_USER": b64(instance.pg_username),
            "POSTGRES_DB": b64(instance.pg_db_name),
        },
    }


def pvc_manifest(instance: Instance) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": f"pg-data-{instance.slug}",
            "namespace": instance.k8s_namespace,
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": settings.STORAGE_CLASS,
            "resources": {"requests": {"storage": instance.storage_size}},
        },
    }


def statefulset_manifest(instance: Instance) -> dict:
    """
    StatefulSet with two containers:
      - postgres: the actual PostgreSQL server on port 5432 (not exposed externally)
      - pgbouncer: lightweight connection pooler on port 6432, proxies to localhost:5432
    Users always connect through PgBouncer.
    """
    pool_mode = getattr(instance, "pool_mode", "transaction")
    pool_size = getattr(instance, "pool_size", 20)
    max_client_conn = getattr(instance, "max_client_conn", 100)

    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": instance.k8s_statefulset,
            "namespace": instance.k8s_namespace,
        },
        "spec": {
            "selector": {"matchLabels": {"app": instance.k8s_statefulset}},
            "serviceName": f"pg-{instance.slug}-internal",
            "replicas": 1,
            "template": {
                "metadata": {"labels": {"app": instance.k8s_statefulset}},
                "spec": {
                    "containers": [
                        # ── PostgreSQL ──────────────────────────────────────
                        {
                            "name": "postgres",
                            "image": f"postgres:{instance.pg_version}-alpine",
                            "ports": [{"containerPort": 5432, "name": "postgres"}],
                            "envFrom": [{"secretRef": {"name": instance.k8s_secret_name}}],
                            "resources": {
                                "requests": {
                                    "cpu": instance.cpu_request,
                                    "memory": instance.mem_request,
                                },
                                "limits": {
                                    "cpu": instance.cpu_limit,
                                    "memory": instance.mem_limit,
                                },
                            },
                            "volumeMounts": [
                                {
                                    "name": "pg-data",
                                    "mountPath": "/var/lib/postgresql/data",
                                }
                            ],
                            "readinessProbe": {
                                "exec": {
                                    "command": [
                                        "pg_isready",
                                        "-U", instance.pg_username,
                                        "-d", instance.pg_db_name,
                                    ]
                                },
                                "initialDelaySeconds": 10,
                                "periodSeconds": 5,
                                "failureThreshold": 12,
                            },
                            "livenessProbe": {
                                "exec": {
                                    "command": [
                                        "pg_isready",
                                        "-U", instance.pg_username,
                                        "-d", instance.pg_db_name,
                                    ]
                                },
                                "initialDelaySeconds": 30,
                                "periodSeconds": 10,
                            },
                        },
                        # ── PgBouncer sidecar ───────────────────────────────
                        {
                            "name": "pgbouncer",
                            "image": "bitnami/pgbouncer:latest",
                            "ports": [{"containerPort": PGBOUNCER_PORT, "name": "pgbouncer"}],
                            "env": [
                                # Where PgBouncer connects to (same pod, loopback)
                                {"name": "POSTGRESQL_HOST", "value": "localhost"},
                                {"name": "POSTGRESQL_PORT", "value": "5432"},
                                # Credentials from the same Secret
                                {
                                    "name": "POSTGRESQL_USERNAME",
                                    "valueFrom": {"secretKeyRef": {"name": instance.k8s_secret_name, "key": "POSTGRES_USER"}},
                                },
                                {
                                    "name": "POSTGRESQL_PASSWORD",
                                    "valueFrom": {"secretKeyRef": {"name": instance.k8s_secret_name, "key": "POSTGRES_PASSWORD"}},
                                },
                                {
                                    "name": "POSTGRESQL_DATABASE",
                                    "valueFrom": {"secretKeyRef": {"name": instance.k8s_secret_name, "key": "POSTGRES_DB"}},
                                },
                                # PgBouncer tuning
                                {"name": "PGBOUNCER_PORT", "value": str(PGBOUNCER_PORT)},
                                {"name": "PGBOUNCER_POOL_MODE", "value": pool_mode},
                                {"name": "PGBOUNCER_DEFAULT_POOL_SIZE", "value": str(pool_size)},
                                {"name": "PGBOUNCER_MAX_CLIENT_CONN", "value": str(max_client_conn)},
                                # Required by bitnami image
                                {"name": "PGBOUNCER_AUTH_TYPE", "value": "md5"},
                                {"name": "PGBOUNCER_IGNORE_STARTUP_PARAMETERS", "value": "extra_float_digits"},
                            ],
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "32Mi"},
                                "limits": {"cpu": "200m", "memory": "64Mi"},
                            },
                            "readinessProbe": {
                                "tcpSocket": {"port": PGBOUNCER_PORT},
                                "initialDelaySeconds": 5,
                                "periodSeconds": 5,
                            },
                            "livenessProbe": {
                                "tcpSocket": {"port": PGBOUNCER_PORT},
                                "initialDelaySeconds": 15,
                                "periodSeconds": 10,
                            },
                        },
                    ],
                    "volumes": [
                        {
                            "name": "pg-data",
                            "persistentVolumeClaim": {"claimName": f"pg-data-{instance.slug}"},
                        }
                    ],
                },
            },
        },
    }


def clusterip_service_manifest(instance: Instance) -> dict:
    """Internal service exposes both postgres (5432) and pgbouncer (6432)."""
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"pg-{instance.slug}-internal",
            "namespace": instance.k8s_namespace,
        },
        "spec": {
            "selector": {"app": instance.k8s_statefulset},
            "ports": [
                {"name": "postgres", "port": 5432, "targetPort": 5432},
                {"name": "pgbouncer", "port": PGBOUNCER_PORT, "targetPort": PGBOUNCER_PORT},
            ],
            "type": "ClusterIP",
        },
    }


def external_service_manifest(instance: Instance) -> dict:
    """
    External service routes to PgBouncer (6432) — users always go through the pooler.
    PostgreSQL port 5432 is never exposed externally.
    """
    svc_type = "LoadBalancer" if settings.ENVIRONMENT == "prod" else "NodePort"
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"pg-{instance.slug}-external",
            "namespace": instance.k8s_namespace,
            "annotations": {
                "arc.io/pool-mode": getattr(instance, "pool_mode", "transaction"),
                "arc.io/pool-size": str(getattr(instance, "pool_size", 20)),
            },
        },
        "spec": {
            "selector": {"app": instance.k8s_statefulset},
            "ports": [
                {
                    "name": "pgbouncer",
                    "port": PGBOUNCER_PORT,
                    "targetPort": PGBOUNCER_PORT,
                    "protocol": "TCP",
                }
            ],
            "type": svc_type,
        },
    }
