from functools import lru_cache

from kubernetes import client, config

from api.config import settings


@lru_cache(maxsize=1)
def get_k8s_client() -> client.ApiClient:
    if settings.K8S_IN_CLUSTER:
        config.load_incluster_config()
    else:
        kubeconfig = settings.KUBECONFIG_PATH or None
        config.load_kube_config(config_file=kubeconfig)
    return client.ApiClient()
