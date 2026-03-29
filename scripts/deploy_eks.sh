#!/usr/bin/env bash
# deploy_eks.sh — Full EKS deployment for Arc
# Usage: ./scripts/deploy_eks.sh [--skip-terraform] [--image-tag latest]
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TF_DIR="${REPO_ROOT}/terraform"
K8S_DIR="${REPO_ROOT}/k8s"

IMAGE_TAG="${IMAGE_TAG:-latest}"
SKIP_TERRAFORM=false

for arg in "$@"; do
  case $arg in
    --skip-terraform) SKIP_TERRAFORM=true ;;
    --image-tag=*)    IMAGE_TAG="${arg#*=}" ;;
  esac
done

# ── Prerequisites ─────────────────────────────────────────────────────────────
for cmd in terraform aws kubectl docker; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd not found in PATH"; exit 1; }
done

# ── Step 1: Terraform ─────────────────────────────────────────────────────────
if [ "$SKIP_TERRAFORM" = false ]; then
  echo "==> Running Terraform..."
  cd "${TF_DIR}"
  terraform init -upgrade
  terraform apply -auto-approve
  cd "${REPO_ROOT}"
fi

# ── Step 2: Read Terraform outputs ───────────────────────────────────────────
echo "==> Reading Terraform outputs..."
cd "${TF_DIR}"
CLUSTER_NAME=$(terraform output -raw cluster_name)
ECR_URL=$(terraform output -raw ecr_repository_url)
AWS_REGION=$(terraform output -raw cluster_name | xargs -I{} aws eks describe-cluster --name {} --query 'cluster.arn' --output text 2>/dev/null | cut -d: -f4 || echo "us-east-1")
cd "${REPO_ROOT}"

# ── Step 3: Configure kubectl ─────────────────────────────────────────────────
echo "==> Configuring kubectl for cluster: ${CLUSTER_NAME}..."
aws eks update-kubeconfig --name "${CLUSTER_NAME}" --alias "${CLUSTER_NAME}"

# ── Step 4: Apply gp3 StorageClass ───────────────────────────────────────────
echo "==> Applying gp3 StorageClass..."
kubectl apply -f "${TF_DIR}/rendered/storageclass-gp3.yaml"

# Patch default StorageClass annotation off the old gp2
kubectl get storageclass gp2 >/dev/null 2>&1 && \
  kubectl patch storageclass gp2 -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"false"}}}' || true

# ── Step 5: Build & push Arc API image ───────────────────────────────────────
echo "==> Logging in to ECR..."
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_URL%/*}"

echo "==> Building Arc API image (tag: ${IMAGE_TAG})..."
docker build -t "arc-api:${IMAGE_TAG}" "${REPO_ROOT}"
docker tag "arc-api:${IMAGE_TAG}" "${ECR_URL}:${IMAGE_TAG}"

echo "==> Pushing to ECR..."
docker push "${ECR_URL}:${IMAGE_TAG}"

# ── Step 6: Apply RBAC ────────────────────────────────────────────────────────
echo "==> Applying RBAC..."
kubectl apply -f "${K8S_DIR}/rbac/"

# ── Step 7: Apply API Deployment ─────────────────────────────────────────────
echo "==> Applying Arc API deployment..."
# Substitute the ECR image URL placeholder
sed "s|ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/arc-api:latest|${ECR_URL}:${IMAGE_TAG}|g" \
  "${K8S_DIR}/api-deployment.yaml" | kubectl apply -f -

# ── Step 8: Wait for rollout ──────────────────────────────────────────────────
echo "==> Waiting for Arc API rollout..."
kubectl rollout status deployment/arc-api -n arc-system --timeout=300s

# ── Step 9: Print endpoint ────────────────────────────────────────────────────
echo ""
echo "==> Arc API is live!"
LB_HOST=$(kubectl get svc arc-api -n arc-system -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "(pending)")
echo "    Load Balancer: ${LB_HOST}"
echo "    Health check:  http://${LB_HOST}/health"
echo ""
echo "    To run migrations:"
echo "    kubectl exec -n arc-system deploy/arc-api -- alembic upgrade head"
