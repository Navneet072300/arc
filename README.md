# TuskDB

> Serverless PostgreSQL as a Service, running on Kubernetes.
> Provision isolated PostgreSQL instances on demand — no infrastructure management required.

---

## Overview

TuskDB is a self-hosted serverless database platform that lets users spin up managed PostgreSQL instances through a REST API or web dashboard. Each instance runs in its own Kubernetes namespace with dedicated storage, credentials, and networking. Users never touch Kubernetes — they just get a connection string.

**Inspired by:** Neon, Supabase, Render Postgres
**Runs on:** AWS EKS (production) · minikube (local development)

---

## Architecture

```
                        ┌─────────────────────────────────────────┐
                        │               AWS EKS Cluster            │
                        │                                          │
  Users ──► ALB ──► ┌──┴──────────┐     ┌──────────────────────┐ │
                     │  TuskDB API │────►│  pg-<id>-<name>      │ │
                     │  (FastAPI)  │     │  ┌──────────────────┐│ │
                     └──────┬──────┘     │  │ StatefulSet (PG) ││ │
                            │            │  │ Secret           ││ │
                     ┌──────▼──────┐     │  │ PVC (EBS gp3)   ││ │
                     │  RDS        │     │  │ NodePort Svc     ││ │
                     │  PostgreSQL │     │  └──────────────────┘│ │
                     │ (control    │     └──────────────────────┘ │
                     │  plane)     │     ┌──────────────────────┐ │
                     └─────────────┘     │  pg-<id>-<name>      │ │
                                         │  (another user)      │ │
                                         └──────────────────────┘ │
                        └─────────────────────────────────────────┘
```

**Control plane** (RDS PostgreSQL) — stores users, instances metadata, billing records
**Data plane** (EKS) — runs one K8s namespace per PostgreSQL instance, fully isolated

---

## Features

- **On-demand provisioning** — create a PostgreSQL instance in seconds via API or dashboard
- **Full isolation** — each instance gets its own K8s namespace, StatefulSet, PVC, and credentials
- **Credential management** — passwords never stored in the control plane; rotate anytime
- **Usage metering** — CPU, memory, and storage tracked every 60 seconds via Metrics Server
- **Billing** — daily aggregation into cost summaries (USD)
- **Web dashboard** — Supabase-inspired dark UI; no build step required
- **JWT authentication** — access tokens + refresh tokens
- **EKS-ready** — NodePort for local dev, LoadBalancer for EKS; toggled by one env var

---

## Tech Stack

| Layer | Technology |
|---|---|
| API | Python 3.12, FastAPI, Uvicorn |
| Database (control plane) | PostgreSQL 16 (RDS on EKS) |
| ORM / Migrations | SQLAlchemy async, Alembic |
| Auth | JWT (python-jose), bcrypt |
| Kubernetes client | kubernetes Python SDK |
| Metering scheduler | APScheduler |
| Dashboard | Vanilla HTML/CSS/JS (no build step) |
| Container runtime | Docker |
| Orchestration | Kubernetes — AWS EKS |
| Storage | AWS EBS (gp3 StorageClass) |

---

## Project Structure

```
tuskdb/
├── api/
│   ├── main.py               # App factory, lifespan, scheduler
│   ├── config.py             # All settings via env vars
│   ├── dependencies.py       # JWT auth dependency
│   ├── auth/                 # Register, login, refresh, logout
│   ├── users/                # Profile management
│   ├── instances/            # Provision / deprovision / rotate creds
│   ├── billing/              # Usage queries, monthly summaries
│   ├── metering/             # Background collector (APScheduler)
│   ├── k8s/
│   │   ├── client.py         # K8s client init (in-cluster / kubeconfig)
│   │   ├── manifests.py      # Pure Python K8s resource builders
│   │   ├── provisioner.py    # Namespace → Secret → PVC → StatefulSet → Services
│   │   └── exceptions.py
│   └── db/
│       ├── models/           # User, Instance, UsageRecord, BillingSummary, AuditLog
│       └── migrations/       # Alembic async migrations
├── dashboard/
│   ├── index.html            # Login / Register
│   ├── app/index.html        # Instance dashboard
│   └── billing/index.html    # Usage & billing
├── k8s/
│   ├── rbac/                 # ClusterRole, ServiceAccount, Binding
│   └── api-deployment.yaml   # TuskDB API deployment manifest
├── scripts/
│   ├── setup_minikube.sh     # Local dev bootstrap
│   └── seed_db.sh            # Insert test admin user
├── tests/                    # pytest, httpx, mocked K8s client
├── docker-compose.yml        # Local control-plane Postgres
├── Dockerfile
└── requirements.txt
```

---

## Local Development (minikube)

### Prerequisites

- Python 3.12+
- Docker Desktop
- [minikube](https://minikube.sigs.k8s.io/docs/start/)
- kubectl

### Setup

```bash
# 1. Clone and enter the project
git clone https://github.com/your-org/tuskdb.git
cd tuskdb

# 2. Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set SECRET_KEY to a random hex string:
# python3 -c "import secrets; print(secrets.token_hex(32))"

# 4. Start minikube + control-plane DB + apply RBAC
./scripts/setup_minikube.sh

# 5. Start the API
uvicorn api.main:app --reload
```

Open **http://localhost:8000/ui** for the dashboard
Open **http://localhost:8000/docs** for the interactive API docs

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Control-plane DB connection string |
| `SECRET_KEY` | — | JWT signing secret (32-byte hex) |
| `JWT_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `K8S_IN_CLUSTER` | `false` | Set to `true` when running inside a pod |
| `KUBECONFIG_PATH` | `~/.kube/config` | Path to kubeconfig (local dev only) |
| `ENVIRONMENT` | `dev` | `dev` = NodePort services, `prod` = LoadBalancer |
| `STORAGE_CLASS` | `standard` | `standard` (minikube) or `gp3` (EKS) |
| `METERING_INTERVAL_SECS` | `60` | How often to poll K8s Metrics Server |

---

## Deployment on AWS EKS

> EKS deployment guide — full setup will be published shortly. Summary of steps below.

### 1. Create EKS Cluster

```bash
eksctl create cluster \
  --name tuskdb \
  --region us-east-1 \
  --nodegroup-name standard-workers \
  --node-type t3.medium \
  --nodes 2 \
  --nodes-min 1 \
  --nodes-max 4 \
  --managed
```

### 2. Install AWS Load Balancer Controller

Required so that `LoadBalancer` services get an NLB automatically.

```bash
helm repo add eks https://aws.github.io/eks-charts
helm install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=tuskdb
```

### 3. Enable Metrics Server

```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### 4. Apply RBAC

```bash
kubectl apply -f k8s/rbac/
```

### 5. Create the API secret

```bash
kubectl create secret generic serverless-pg-api-env \
  --from-literal=DATABASE_URL="postgresql+asyncpg://user:pass@rds-endpoint:5432/tuskdb" \
  --from-literal=SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

### 6. Build and push Docker image

```bash
# Authenticate with ECR
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com

# Build and push
docker build -t tuskdb-api .
docker tag tuskdb-api:latest <account>.dkr.ecr.us-east-1.amazonaws.com/tuskdb-api:latest
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/tuskdb-api:latest
```

Update the image in `k8s/api-deployment.yaml`, then:

```bash
kubectl apply -f k8s/api-deployment.yaml
```

### 7. Set production env vars

```bash
ENVIRONMENT=prod
STORAGE_CLASS=gp3
K8S_IN_CLUSTER=true
```

### Key difference from minikube

| Setting | minikube | EKS |
|---|---|---|
| `ENVIRONMENT` | `dev` | `prod` |
| `STORAGE_CLASS` | `standard` | `gp3` |
| `K8S_IN_CLUSTER` | `false` | `true` |
| PostgreSQL service type | `NodePort` | `LoadBalancer` (NLB) |
| Control-plane DB | Docker Compose | AWS RDS |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/register` | Create account |
| `POST` | `/auth/login` | Login, returns JWT pair |
| `POST` | `/auth/refresh` | Refresh access token |
| `POST` | `/auth/logout` | Revoke refresh token |
| `GET` | `/users/me` | Get current user profile |
| `GET` | `/instances` | List all instances |
| `POST` | `/instances` | Provision a new instance (202 async) |
| `GET` | `/instances/{id}` | Get instance detail + connection string |
| `GET` | `/instances/{id}/status` | Poll provisioning status |
| `DELETE` | `/instances/{id}` | Deprovision instance (202 async) |
| `POST` | `/instances/{id}/credentials/rotate` | Rotate PostgreSQL password |
| `GET` | `/billing/usage` | Query usage (hourly/daily) |
| `GET` | `/billing/summaries` | List monthly billing summaries |
| `GET` | `/health` | Health check (DB + K8s) |

Full interactive docs: `http://localhost:8000/docs`

---

## Per-Instance Kubernetes Resources

Every provisioned instance creates the following resources inside its own namespace `pg-<user_id>-<name>`:

```
Namespace
└── Secret          (pg-creds-<slug>)      — POSTGRES_PASSWORD, POSTGRES_USER, POSTGRES_DB
└── PVC             (pg-data-<slug>)       — EBS gp3 volume
└── StatefulSet     (pg-<slug>)            — postgres:16-alpine, 1 replica
└── Service/ClusterIP  (pg-<slug>-internal)
└── Service/LoadBalancer (pg-<slug>-external) — user-facing endpoint
```

Deprovisioning deletes the namespace — Kubernetes cascades all child resources automatically.

---

## Running Tests

```bash
# Tests use SQLite in-memory and mock the K8s client — no cluster needed
pytest

# With coverage
pytest --cov=api --cov-report=term-missing
```

---

## Roadmap

- [ ] EKS deployment (coming soon)
- [ ] Connection pooling with PgBouncer
- [ ] Point-in-time recovery (PITR)
- [ ] Read replicas
- [ ] Scale-to-zero (suspend idle instances)
- [ ] Webhook notifications on instance events
- [ ] Admin panel
- [ ] Terraform module for EKS + RDS setup

---

## License

MIT
# arc
