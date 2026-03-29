#!/usr/bin/env bash
# deploy_eks.sh — Full EKS deployment for Arc
# Usage: ./scripts/deploy_eks.sh [--skip-terraform] [--skip-build] [--image-tag TAG]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TF_DIR="${REPO_ROOT}/terraform"
K8S_DIR="${REPO_ROOT}/k8s"

IMAGE_TAG="${IMAGE_TAG:-latest}"
SKIP_TERRAFORM=false
SKIP_BUILD=false

for arg in "$@"; do
  case $arg in
    --skip-terraform) SKIP_TERRAFORM=true ;;
    --skip-build)     SKIP_BUILD=true ;;
    --image-tag=*)    IMAGE_TAG="${arg#*=}" ;;
  esac
done

# ── Prerequisites ─────────────────────────────────────────────────────────────
for cmd in terraform aws kubectl docker; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERROR: $cmd not found in PATH"; exit 1; }
done

# ── Step 1: Terraform ─────────────────────────────────────────────────────────
if [ "$SKIP_TERRAFORM" = false ]; then
  echo "==> [1/8] Running Terraform..."
  cd "${TF_DIR}"
  terraform init -upgrade
  terraform apply -auto-approve
  cd "${REPO_ROOT}"
fi

# ── Step 2: Read Terraform outputs ───────────────────────────────────────────
echo "==> [2/8] Reading Terraform outputs..."
cd "${TF_DIR}"
CLUSTER_NAME=$(terraform output -raw cluster_name)
ECR_URL=$(terraform output -raw ecr_repository_url)
AWS_REGION=$(terraform output -raw cluster_name \
  | xargs -I{} aws eks describe-cluster --name {} \
      --query 'cluster.arn' --output text \
  | cut -d: -f4)
cd "${REPO_ROOT}"

echo "    Cluster : ${CLUSTER_NAME}"
echo "    ECR     : ${ECR_URL}"
echo "    Region  : ${AWS_REGION}"

# ── Step 3: Configure kubectl ─────────────────────────────────────────────────
echo "==> [3/8] Configuring kubectl..."
aws eks update-kubeconfig --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}" --alias "${CLUSTER_NAME}"

# ── Step 4: Base cluster setup ────────────────────────────────────────────────
echo "==> [4/8] Applying base cluster resources..."
kubectl apply -f "${K8S_DIR}/namespace.yaml"
kubectl apply -f "${K8S_DIR}/storageclass.yaml"
kubectl apply -f "${K8S_DIR}/metrics-server.yaml"
kubectl apply -f "${K8S_DIR}/rbac/"

# ── Step 5: Build & push Arc API image ───────────────────────────────────────
if [ "$SKIP_BUILD" = false ]; then
  echo "==> [5/8] Building and pushing Arc API image (tag: ${IMAGE_TAG})..."
  aws ecr get-login-password --region "${AWS_REGION}" \
    | docker login --username AWS --password-stdin "${ECR_URL%/*}"

  docker build -t "arc-api:${IMAGE_TAG}" "${REPO_ROOT}"
  docker tag "arc-api:${IMAGE_TAG}" "${ECR_URL}:${IMAGE_TAG}"
  docker push "${ECR_URL}:${IMAGE_TAG}"
else
  echo "==> [5/8] Skipping image build (--skip-build)"
fi

# ── Step 6: Run database migrations ──────────────────────────────────────────
echo "==> [6/8] Running database migrations..."
# Substitute image URL and apply as a one-off Job
sed "s|ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/arc-api:latest|${ECR_URL}:${IMAGE_TAG}|g" \
  "${K8S_DIR}/migration-job.yaml" \
  | kubectl apply -f -

echo "    Waiting for migration job to complete (timeout: 3m)..."
kubectl wait job/arc-migrate -n arc-system \
  --for=condition=complete --timeout=180s \
  || { echo "ERROR: Migration job failed"; kubectl logs -n arc-system -l app=arc-migrate --tail=50; exit 1; }

# ── Step 7: Deploy Arc API ────────────────────────────────────────────────────
echo "==> [7/8] Deploying Arc API..."
sed "s|ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com/arc-api:latest|${ECR_URL}:${IMAGE_TAG}|g" \
  "${K8S_DIR}/api-deployment.yaml" \
  | kubectl apply -f -

echo "    Waiting for rollout..."
kubectl rollout status deployment/arc-api -n arc-system --timeout=300s

# ── Step 8: Print summary ─────────────────────────────────────────────────────
echo ""
echo "==> [8/8] Arc is live!"
LB=$(kubectl get svc arc-api -n arc-system \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "(pending — wait ~2 min)")
echo ""
echo "    API endpoint : http://${LB}"
echo "    Health check : http://${LB}/health"
echo "    Dashboard    : http://${LB}/ui"
echo ""
echo "    To tail API logs:"
echo "    kubectl logs -n arc-system -l app=arc-api -f"
