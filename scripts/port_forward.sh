#!/usr/bin/env bash
# Port-forward the API service when deployed in-cluster (minikube)
set -euo pipefail

echo "Port-forwarding serverless-pg-api → http://localhost:8000"
kubectl port-forward svc/serverless-pg-api 8000:80
