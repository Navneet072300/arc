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


def secret_manifest(instance: Instance, password: str, replication_password: str = "") -> dict:
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
            "POSTGRES_REPLICATION_PASSWORD": b64(replication_password or password),
        },
    }


def replication_config_manifest(instance: Instance) -> dict:
    """ConfigMap with an initdb script that creates the replication user and tunes WAL."""
    script = (
        "#!/bin/bash\n"
        "set -e\n"
        "psql -v ON_ERROR_STOP=1 --username \"$POSTGRES_USER\" <<-EOSQL\n"
        "  CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '$POSTGRES_REPLICATION_PASSWORD';\n"
        "EOSQL\n"
        "echo \"host replication replicator all md5\" >> \"$PGDATA/pg_hba.conf\"\n"
    )
    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": f"pg-init-{instance.slug}",
            "namespace": instance.k8s_namespace,
        },
        "data": {"init-replication.sh": script},
    }


def wal_archive_pvc_manifest(instance: Instance) -> dict:
    """Dedicated PVC for continuous WAL archiving — enables PITR."""
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": f"pg-wal-{instance.slug}",
            "namespace": instance.k8s_namespace,
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": settings.STORAGE_CLASS,
            # WAL archive needs ≈ 2× data size; default 10 Gi is a reasonable floor
            "resources": {"requests": {"storage": "10Gi"}},
        },
    }


def pvc_manifest_for_slug(instance: Instance, slug: str) -> dict:
    """Generic data PVC for any slug (used for restored instances)."""
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": f"pg-data-{slug}",
            "namespace": instance.k8s_namespace,
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": settings.STORAGE_CLASS,
            "resources": {"requests": {"storage": instance.storage_size}},
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
                            # WAL streaming replication + continuous archiving for PITR
                            "args": [
                                "-c", "wal_level=replica",
                                "-c", "max_wal_senders=10",
                                "-c", "wal_keep_size=64",
                                "-c", "hot_standby=on",
                                "-c", "archive_mode=on",
                                "-c", (
                                    "archive_command="
                                    "test ! -f /var/lib/postgresql/wal_archive/%f "
                                    "&& cp %p /var/lib/postgresql/wal_archive/%f"
                                ),
                            ],
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
                                },
                                {
                                    "name": "init-scripts",
                                    "mountPath": "/docker-entrypoint-initdb.d",
                                },
                                {
                                    "name": "wal-archive",
                                    "mountPath": "/var/lib/postgresql/wal_archive",
                                },
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
                        },
                        {
                            "name": "init-scripts",
                            "configMap": {
                                "name": f"pg-init-{instance.slug}",
                                "defaultMode": 0o755,
                            },
                        },
                        {
                            "name": "wal-archive",
                            "persistentVolumeClaim": {"claimName": f"pg-wal-{instance.slug}"},
                        },
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


def replica_pvc_manifest(instance: Instance, replica_slug: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": f"pg-data-{replica_slug}",
            "namespace": instance.k8s_namespace,
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": settings.STORAGE_CLASS,
            "resources": {"requests": {"storage": instance.storage_size}},
        },
    }


def replica_statefulset_manifest(instance: Instance, replica_slug: str) -> dict:
    """
    Read-replica StatefulSet:
    - init container: pg_basebackup from the primary's internal ClusterIP service
    - main container: postgres in hot_standby mode (data already seeded)
    - pgbouncer sidecar: pools read-only connections on port 6432
    """
    pool_mode = getattr(instance, "pool_mode", "transaction")
    pool_size = getattr(instance, "pool_size", 20)
    max_client_conn = getattr(instance, "max_client_conn", 100)
    primary_svc = f"pg-{instance.slug}-internal"
    sts_name = f"pg-{replica_slug}"

    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": sts_name,
            "namespace": instance.k8s_namespace,
            "labels": {"arc.io/role": "replica"},
        },
        "spec": {
            "selector": {"matchLabels": {"app": sts_name}},
            "serviceName": f"pg-{replica_slug}-internal",
            "replicas": 1,
            "template": {
                "metadata": {"labels": {"app": sts_name, "arc.io/role": "replica"}},
                "spec": {
                    "initContainers": [
                        {
                            "name": "pg-basebackup",
                            "image": f"postgres:{instance.pg_version}-alpine",
                            "command": [
                                "sh", "-c",
                                (
                                    "until pg_isready -h %(svc)s -p 5432"
                                    " -U %(user)s; do sleep 2; done; "
                                    "pg_basebackup -h %(svc)s -p 5432"
                                    " -U replicator -D /var/lib/postgresql/data"
                                    " -Xs -R -P --checkpoint=fast"
                                ) % {"svc": primary_svc, "user": instance.pg_username},
                            ],
                            "env": [
                                {
                                    "name": "PGPASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": instance.k8s_secret_name,
                                            "key": "POSTGRES_REPLICATION_PASSWORD",
                                        }
                                    },
                                }
                            ],
                            "volumeMounts": [
                                {"name": "pg-data", "mountPath": "/var/lib/postgresql/data"}
                            ],
                        }
                    ],
                    "containers": [
                        # ── PostgreSQL (hot standby) ─────────────────────────
                        {
                            "name": "postgres",
                            "image": f"postgres:{instance.pg_version}-alpine",
                            "args": ["-c", "hot_standby=on"],
                            "ports": [{"containerPort": 5432, "name": "postgres"}],
                            "env": [
                                # PGDATA must point to the seeded directory
                                {"name": "PGDATA", "value": "/var/lib/postgresql/data"},
                                # Required by image even in standby (won't be used)
                                {
                                    "name": "POSTGRES_PASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": instance.k8s_secret_name,
                                            "key": "POSTGRES_PASSWORD",
                                        }
                                    },
                                },
                            ],
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
                                {"name": "pg-data", "mountPath": "/var/lib/postgresql/data"}
                            ],
                            "readinessProbe": {
                                "exec": {
                                    "command": [
                                        "pg_isready",
                                        "-U", instance.pg_username,
                                        "-d", instance.pg_db_name,
                                    ]
                                },
                                "initialDelaySeconds": 15,
                                "periodSeconds": 5,
                                "failureThreshold": 12,
                            },
                        },
                        # ── PgBouncer sidecar ───────────────────────────────
                        {
                            "name": "pgbouncer",
                            "image": "bitnami/pgbouncer:latest",
                            "ports": [{"containerPort": PGBOUNCER_PORT, "name": "pgbouncer"}],
                            "env": [
                                {"name": "POSTGRESQL_HOST", "value": "localhost"},
                                {"name": "POSTGRESQL_PORT", "value": "5432"},
                                {
                                    "name": "POSTGRESQL_USERNAME",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": instance.k8s_secret_name,
                                            "key": "POSTGRES_USER",
                                        }
                                    },
                                },
                                {
                                    "name": "POSTGRESQL_PASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": instance.k8s_secret_name,
                                            "key": "POSTGRES_PASSWORD",
                                        }
                                    },
                                },
                                {
                                    "name": "POSTGRESQL_DATABASE",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": instance.k8s_secret_name,
                                            "key": "POSTGRES_DB",
                                        }
                                    },
                                },
                                {"name": "PGBOUNCER_PORT", "value": str(PGBOUNCER_PORT)},
                                {"name": "PGBOUNCER_POOL_MODE", "value": pool_mode},
                                {"name": "PGBOUNCER_DEFAULT_POOL_SIZE", "value": str(pool_size)},
                                {"name": "PGBOUNCER_MAX_CLIENT_CONN", "value": str(max_client_conn)},
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
                        },
                    ],
                    "volumes": [
                        {
                            "name": "pg-data",
                            "persistentVolumeClaim": {"claimName": f"pg-data-{replica_slug}"},
                        }
                    ],
                },
            },
        },
    }


def replica_service_manifest(instance: Instance, replica_slug: str) -> dict:
    """External service (NodePort / LoadBalancer) for the read replica."""
    svc_type = "LoadBalancer" if settings.ENVIRONMENT == "prod" else "NodePort"
    sts_name = f"pg-{replica_slug}"
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"pg-{replica_slug}-external",
            "namespace": instance.k8s_namespace,
            "annotations": {"arc.io/role": "replica"},
        },
        "spec": {
            "selector": {"app": sts_name},
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


# ── PITR: Backup & Restore ───────────────────────────────────────────────────

def backup_pvc_manifest(instance: Instance, backup_slug: str) -> dict:
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": f"pg-backup-{backup_slug}",
            "namespace": instance.k8s_namespace,
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": settings.STORAGE_CLASS,
            "resources": {"requests": {"storage": instance.storage_size}},
        },
    }


def backup_job_manifest(instance: Instance, backup_slug: str) -> dict:
    """
    K8s Job that runs pg_basebackup from the primary into a dedicated backup PVC.
    Uses the replicator user + replication password from the instance Secret.
    """
    primary_svc = f"pg-{instance.slug}-internal"
    job_name = f"pg-backup-{backup_slug}"

    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": instance.k8s_namespace,
            "labels": {"arc.io/backup-slug": backup_slug},
        },
        "spec": {
            "ttlSecondsAfterFinished": 3600,  # auto-clean job after 1 hour
            "backoffLimit": 2,
            "template": {
                "metadata": {"labels": {"arc.io/backup-slug": backup_slug}},
                "spec": {
                    "restartPolicy": "OnFailure",
                    "containers": [
                        {
                            "name": "pg-basebackup",
                            "image": f"postgres:{instance.pg_version}-alpine",
                            "command": [
                                "sh", "-c",
                                (
                                    "until pg_isready -h %(svc)s -p 5432"
                                    " -U %(user)s; do sleep 2; done; "
                                    "pg_basebackup -h %(svc)s -p 5432"
                                    " -U replicator -D /backup/data"
                                    " -Xs -P --checkpoint=fast"
                                    " && echo DONE"
                                ) % {"svc": primary_svc, "user": instance.pg_username},
                            ],
                            "env": [
                                {
                                    "name": "PGPASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": instance.k8s_secret_name,
                                            "key": "POSTGRES_REPLICATION_PASSWORD",
                                        }
                                    },
                                }
                            ],
                            "volumeMounts": [
                                {"name": "backup", "mountPath": "/backup"},
                                {"name": "wal-archive", "mountPath": "/wal_archive", "readOnly": True},
                            ],
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "500m", "memory": "256Mi"},
                            },
                        }
                    ],
                    "volumes": [
                        {
                            "name": "backup",
                            "persistentVolumeClaim": {"claimName": f"pg-backup-{backup_slug}"},
                        },
                        {
                            "name": "wal-archive",
                            "persistentVolumeClaim": {"claimName": f"pg-wal-{instance.slug}"},
                        },
                    ],
                },
            },
        },
    }


def restore_statefulset_manifest(
    instance: Instance,
    backup_slug: str,
    restored_slug: str,
    recovery_target_time: str | None = None,
) -> dict:
    """
    StatefulSet for a restored instance.
    An init container copies the backup PVC data into the new data PVC,
    then writes postgresql.auto.conf with recovery settings.
    """
    sts_name = f"pg-{restored_slug}"

    # Build recovery settings for PITR
    recovery_lines = [
        "restore_command = 'cp /wal_archive/%f %p'",
    ]
    if recovery_target_time:
        recovery_lines.append(f"recovery_target_time = '{recovery_target_time}'")
        recovery_lines.append("recovery_target_action = 'promote'")
    else:
        recovery_lines.append("recovery_target_action = 'promote'")

    recovery_conf = "\\n".join(recovery_lines)

    return {
        "apiVersion": "apps/v1",
        "kind": "StatefulSet",
        "metadata": {
            "name": sts_name,
            "namespace": instance.k8s_namespace,
            "labels": {"arc.io/role": "restored"},
        },
        "spec": {
            "selector": {"matchLabels": {"app": sts_name}},
            "serviceName": f"pg-{restored_slug}-internal",
            "replicas": 1,
            "template": {
                "metadata": {"labels": {"app": sts_name}},
                "spec": {
                    "initContainers": [
                        {
                            "name": "restore-data",
                            "image": f"postgres:{instance.pg_version}-alpine",
                            "command": [
                                "sh", "-c",
                                # Copy backup into data dir, then inject recovery config
                                (
                                    "cp -a /backup/data/. /var/lib/postgresql/data/ "
                                    "&& touch /var/lib/postgresql/data/standby.signal "
                                    f"&& printf '{recovery_conf}\\n' "
                                    ">> /var/lib/postgresql/data/postgresql.auto.conf "
                                    "&& echo 'Restore data initialised'"
                                ),
                            ],
                            "volumeMounts": [
                                {"name": "pg-data", "mountPath": "/var/lib/postgresql/data"},
                                {"name": "backup", "mountPath": "/backup", "readOnly": True},
                                {"name": "wal-archive", "mountPath": "/wal_archive", "readOnly": True},
                            ],
                        }
                    ],
                    "containers": [
                        {
                            "name": "postgres",
                            "image": f"postgres:{instance.pg_version}-alpine",
                            "args": ["-c", "hot_standby=on"],
                            "ports": [{"containerPort": 5432, "name": "postgres"}],
                            "env": [
                                {"name": "PGDATA", "value": "/var/lib/postgresql/data"},
                                {
                                    "name": "POSTGRES_PASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": instance.k8s_secret_name,
                                            "key": "POSTGRES_PASSWORD",
                                        }
                                    },
                                },
                            ],
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
                                {"name": "pg-data", "mountPath": "/var/lib/postgresql/data"},
                                {"name": "wal-archive", "mountPath": "/wal_archive", "readOnly": True},
                            ],
                            "readinessProbe": {
                                "exec": {
                                    "command": [
                                        "pg_isready",
                                        "-U", instance.pg_username,
                                        "-d", instance.pg_db_name,
                                    ]
                                },
                                "initialDelaySeconds": 20,
                                "periodSeconds": 5,
                                "failureThreshold": 24,
                            },
                        },
                        {
                            "name": "pgbouncer",
                            "image": "bitnami/pgbouncer:latest",
                            "ports": [{"containerPort": PGBOUNCER_PORT, "name": "pgbouncer"}],
                            "env": [
                                {"name": "POSTGRESQL_HOST", "value": "localhost"},
                                {"name": "POSTGRESQL_PORT", "value": "5432"},
                                {
                                    "name": "POSTGRESQL_USERNAME",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": instance.k8s_secret_name,
                                            "key": "POSTGRES_USER",
                                        }
                                    },
                                },
                                {
                                    "name": "POSTGRESQL_PASSWORD",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": instance.k8s_secret_name,
                                            "key": "POSTGRES_PASSWORD",
                                        }
                                    },
                                },
                                {
                                    "name": "POSTGRESQL_DATABASE",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": instance.k8s_secret_name,
                                            "key": "POSTGRES_DB",
                                        }
                                    },
                                },
                                {"name": "PGBOUNCER_PORT", "value": str(PGBOUNCER_PORT)},
                                {"name": "PGBOUNCER_POOL_MODE", "value": "transaction"},
                                {"name": "PGBOUNCER_DEFAULT_POOL_SIZE", "value": "20"},
                                {"name": "PGBOUNCER_MAX_CLIENT_CONN", "value": "100"},
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
                        },
                    ],
                    "volumes": [
                        {
                            "name": "pg-data",
                            "persistentVolumeClaim": {"claimName": f"pg-data-{restored_slug}"},
                        },
                        {
                            "name": "backup",
                            "persistentVolumeClaim": {"claimName": f"pg-backup-{backup_slug}"},
                        },
                        {
                            "name": "wal-archive",
                            "persistentVolumeClaim": {"claimName": f"pg-wal-{instance.slug}"},
                        },
                    ],
                },
            },
        },
    }
