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
                        {
                            "name": "postgres",
                            "image": f"postgres:{instance.pg_version}-alpine",
                            "ports": [{"containerPort": 5432}],
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
                                        "-U",
                                        instance.pg_username,
                                        "-d",
                                        instance.pg_db_name,
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
                                        "-U",
                                        instance.pg_username,
                                        "-d",
                                        instance.pg_db_name,
                                    ]
                                },
                                "initialDelaySeconds": 30,
                                "periodSeconds": 10,
                            },
                        }
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
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"pg-{instance.slug}-internal",
            "namespace": instance.k8s_namespace,
        },
        "spec": {
            "selector": {"app": instance.k8s_statefulset},
            "ports": [{"port": 5432, "targetPort": 5432}],
            "type": "ClusterIP",
        },
    }


def external_service_manifest(instance: Instance) -> dict:
    svc_type = "LoadBalancer" if settings.ENVIRONMENT == "prod" else "NodePort"
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"pg-{instance.slug}-external",
            "namespace": instance.k8s_namespace,
        },
        "spec": {
            "selector": {"app": instance.k8s_statefulset},
            "ports": [{"port": 5432, "targetPort": 5432, "protocol": "TCP"}],
            "type": svc_type,
        },
    }
