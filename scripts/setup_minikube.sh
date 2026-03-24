#!/usr/bin/env bash
set -euo pipefail

echo "==> Starting minikube..."
minikube start --cpus=4 --memory=8g --driver=docker

echo "==> Enabling metrics-server addon..."
minikube addons enable metrics-server

echo "==> Applying RBAC..."
kubectl apply -f k8s/rbac/

echo "==> Starting control-plane PostgreSQL (docker-compose)..."
docker compose up -d db

echo "==> Waiting for DB to be ready..."
sleep 5

echo "==> Running migrations..."
python -m alembic -c api/migrations/alembic.ini upgrade head

echo ""
echo "Setup complete!"
echo "Run the API:  uvicorn api.main:app --reload"
echo "Dashboard:    http://localhost:8000/ui"
echo "API docs:     http://localhost:8000/docs"
