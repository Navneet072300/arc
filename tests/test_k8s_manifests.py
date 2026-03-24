"""
Unit tests for k8s manifest builders — no cluster needed.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from api.k8s.manifests import (
    clusterip_service_manifest,
    external_service_manifest,
    namespace_manifest,
    pvc_manifest,
    secret_manifest,
    statefulset_manifest,
)


def make_instance():
    inst = MagicMock()
    inst.id = uuid.uuid4()
    inst.user_id = uuid.uuid4()
    inst.slug = "abcd1234-my-db"
    inst.k8s_namespace = "pg-abcd1234-my-db"
    inst.k8s_statefulset = "pg-abcd1234-my-db"
    inst.k8s_secret_name = "pg-creds-abcd1234-my-db"
    inst.pg_version = "16"
    inst.pg_username = "pguser"
    inst.pg_db_name = "postgres"
    inst.cpu_request = "250m"
    inst.cpu_limit = "500m"
    inst.mem_request = "256Mi"
    inst.mem_limit = "512Mi"
    inst.storage_size = "5Gi"
    return inst


def test_namespace_manifest():
    inst = make_instance()
    m = namespace_manifest(inst)
    assert m["kind"] == "Namespace"
    assert m["metadata"]["name"] == inst.k8s_namespace
    assert m["metadata"]["labels"]["managed-by"] == "serverless-pg"


def test_secret_manifest():
    inst = make_instance()
    m = secret_manifest(inst, "supersecret")
    assert m["kind"] == "Secret"
    assert m["metadata"]["namespace"] == inst.k8s_namespace
    assert "POSTGRES_PASSWORD" in m["data"]
    import base64
    assert base64.b64decode(m["data"]["POSTGRES_PASSWORD"]).decode() == "supersecret"


def test_pvc_manifest():
    inst = make_instance()
    m = pvc_manifest(inst)
    assert m["kind"] == "PersistentVolumeClaim"
    assert m["spec"]["resources"]["requests"]["storage"] == "5Gi"


def test_statefulset_manifest():
    inst = make_instance()
    m = statefulset_manifest(inst)
    assert m["kind"] == "StatefulSet"
    containers = m["spec"]["template"]["spec"]["containers"]
    assert len(containers) == 1
    assert containers[0]["image"] == "postgres:16-alpine"
    assert containers[0]["resources"]["requests"]["cpu"] == "250m"


def test_clusterip_service():
    inst = make_instance()
    m = clusterip_service_manifest(inst)
    assert m["spec"]["type"] == "ClusterIP"
    assert m["spec"]["ports"][0]["port"] == 5432


def test_external_service_dev(monkeypatch):
    monkeypatch.setattr("api.k8s.manifests.settings.ENVIRONMENT", "dev")
    inst = make_instance()
    m = external_service_manifest(inst)
    assert m["spec"]["type"] == "NodePort"


def test_external_service_prod(monkeypatch):
    monkeypatch.setattr("api.k8s.manifests.settings.ENVIRONMENT", "prod")
    inst = make_instance()
    m = external_service_manifest(inst)
    assert m["spec"]["type"] == "LoadBalancer"
