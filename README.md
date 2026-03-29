# Arc — Serverless PostgreSQL Platform

> Self-hosted serverless PostgreSQL as a Service, running on AWS EKS.
> Provision isolated, production-ready PostgreSQL clusters on demand — with connection pooling, scale-to-zero, read replicas, PITR, webhooks, and a full-featured dashboard.

**Inspired by:** Neon · Supabase · Render Postgres

---

## Live Screenshots

### Dashboard — Instance List
![Instance List](docs/screenshots/instances.png)

Manage all your PostgreSQL instances from one place. See status, version, host, port, pooling config, and creation date at a glance.

### Provisioning Form
![New Instance](docs/screenshots/new-instance.png)

Create a new instance with PostgreSQL version, storage size, PgBouncer pool mode, pool size, max client connections, and scale-to-zero idle timeout — all configurable upfront.

### Connection Details
![Connection Details](docs/screenshots/connection-details.png)

After creation, Arc returns a one-time password and full connection string. The password is never stored — rotate it any time via the API or dashboard.

### Billing & Usage
![Billing](docs/screenshots/billing.png)

CPU and memory usage are sampled every 60 seconds per instance. Monthly summaries aggregate usage into estimated cost breakdowns.

### Webhooks
![Webhooks](docs/screenshots/webhooks.png)

Subscribe to lifecycle events and receive HMAC-SHA256 signed HTTP payloads. Supports `instance.provisioning`, `instance.running`, `instance.error`, `instance.deleted`, `credentials.rotated`, and `*` (all events).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            Internet / Users                              │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │  HTTP :80
                      ┌──────────▼──────────┐
                      │    AWS Classic ELB   │
                      └──────────┬──────────┘
                                 │
              ┌──────────────────▼──────────────────┐
              │           arc-system namespace        │
              │                                       │
              │   ┌─────────────────────────────┐    │
              │   │       Arc API (FastAPI)      │    │
              │   │       2–10 pods (HPA)        │    │
              │   │   uvicorn --workers 2        │    │
              │   └──────┬──────────────┬────────┘    │
              │          │              │              │
              └──────────┼──────────────┼──────────────┘
                         │              │
              ┌──────────▼───┐  ┌───────▼──────────────────┐
              │  Amazon RDS   │  │   EKS Node Group          │
              │  PostgreSQL   │  │   (t3.medium × 3)         │
              │  (control DB) │  │                           │
              │  users        │  │  ┌────────────────────┐   │
              │  instances    │  │  │ pg-<slug> namespace │   │
              │  billing      │  │  │                     │   │
              │  webhooks     │  │  │ ┌────────────────┐  │   │
              │  audit_logs   │  │  │ │  StatefulSet   │  │   │
              └───────────────┘  │  │ │ ┌────────────┐ │  │   │
                                 │  │ │ │ PostgreSQL │ │  │   │
                                 │  │ │ │   :5432    │ │  │   │
                                 │  │ │ ├────────────┤ │  │   │
                                 │  │ │ │ PgBouncer  │ │  │   │
                                 │  │ │ │   :6432    │ │  │   │
                                 │  │ │ └────────────┘ │  │   │
                                 │  │ │ PVC (EBS gp3)  │  │   │
                                 │  │ │ Secret (creds) │  │   │
                                 │  │ └────────────────┘  │   │
                                 │  │  (one per instance) │   │
                                 │  └─────────────────────┘   │
                                 └───────────────────────────┘

    CI/CD: GitHub Actions → ECR → EKS
    IaC:   Terraform (VPC · EKS · RDS · ECR)
    State: S3 + DynamoDB lock
```

> **Architecture diagram:** [View on Excalidraw](https://excalidraw.com/#json=arc-architecture)

---

## Features

| Feature | Description |
|---|---|
| **On-demand provisioning** | Create a PostgreSQL cluster in seconds via API or dashboard |
| **Full isolation** | Each instance has its own K8s namespace, StatefulSet, PVC, Secret, and credentials |
| **PgBouncer sidecar** | Connection pooler on port 6432; session, transaction, or statement mode |
| **Scale-to-zero** | StatefulSet scaled to 0 replicas after idle timeout; auto-resumes on demand |
| **Read replicas** | Streaming replication (`wal_level=replica`); replicas as separate StatefulSets |
| **PITR** | WAL archiving to S3; restore to any point in time |
| **Webhooks** | HMAC-SHA256 signed event delivery; 3 retries with exponential backoff |
| **Metering** | CPU/memory sampled every 60s via Kubernetes Metrics Server |
| **Billing** | Monthly usage aggregation with cost estimates |
| **Admin panel** | User management, instance oversight, billing trigger |
| **CI/CD** | GitHub Actions: test → build (ECR) → migrate → deploy (EKS) |
| **HPA** | Arc API auto-scales 2–10 pods on CPU/memory pressure |
| **PodDisruptionBudget** | Minimum 1 API pod always available during node drain |

---

## Technology Stack

### Control Plane

| Component | Technology |
|---|---|
| API framework | FastAPI (Python 3.12) + Uvicorn |
| Database ORM | SQLAlchemy 2.0 async + asyncpg |
| Auth | JWT (python-jose) + bcrypt |
| Background scheduler | APScheduler (metering, billing, idle checks) |
| Migrations | Alembic (async) |
| Config | pydantic-settings |
| HTTP client | httpx |

### Infrastructure

| Component | Technology |
|---|---|
| Kubernetes | Amazon EKS 1.31 — managed node group (t3.medium × 3) |
| Container registry | Amazon ECR |
| Control plane DB | Amazon RDS PostgreSQL 16 (db.t3.micro, gp3, encrypted) |
| Block storage | AWS EBS gp3 (via EBS CSI driver) |
| Load balancer | AWS Classic ELB |
| IaC | Terraform ≥ 1.6 (VPC · EKS · RDS · ECR modules) |
| Terraform state | S3 bucket + DynamoDB lock table |

### Per-Instance Stack

| Component | Technology |
|---|---|
| Database | PostgreSQL 16-alpine (StatefulSet, 1 replica) |
| Connection pooler | PgBouncer (sidecar container on port 6432) |
| Replication | PostgreSQL streaming replication (`wal_level=replica`) |
| Storage | AWS EBS gp3 PersistentVolumeClaim |
| Isolation | Dedicated Kubernetes namespace per instance |
| Credentials | Kubernetes Secret (never stored in Arc DB) |

### Frontend & CI/CD

| Component | Technology |
|---|---|
| Dashboard | Next.js 14 (static export, served via FastAPI StaticFiles at `/ui`) |
| Docker build | Multi-stage: Node 20-alpine (Next.js build) → Python 3.12-slim |
| Tests | pytest + pytest-asyncio + postgres:16 service container |
| Pipeline | GitHub Actions: test → docker buildx → ECR push → kubectl deploy |

---

## Key Services Explained

### PgBouncer — Connection Pooling
Every PostgreSQL instance runs a PgBouncer sidecar. Clients connect on **port 6432** (not 5432 directly). PgBouncer maintains a pool of server-side connections and multiplexes client connections — critical for serverless workloads where connections spike unpredictably.

- **Transaction mode** (default) — connection returned to pool after each transaction. Best for serverless.
- **Session mode** — one server connection per client session. Best for long-lived applications.
- **Statement mode** — connection returned after each statement.

### Scale-to-Zero
APScheduler checks CPU metrics every minute. When an instance's CPU falls below threshold for longer than `idle_timeout_minutes`:
1. `StatefulSet.replicas` is set to `0` — pods terminate, PVC is retained
2. Status changes to `suspended`
3. On resume: replicas set back to `1`, pod starts, connection available in ~15 seconds

### Webhooks
When instance lifecycle events occur, Arc:
1. Queries all active webhook endpoints subscribed to that event
2. Creates a `WebhookDelivery` record
3. Fires an HMAC-SHA256 signed HTTP POST to the endpoint URL
4. Retries up to 3 times with exponential backoff (5s → 25s → 125s)
5. Records status (`success` / `failed`) and response body per attempt

### Provisioning Flow
```
POST /instances
    │
    ├─► Create DB record (status: provisioning)
    ├─► Return 202 Accepted + credentials
    │
    └─► Background task:
            Namespace → Secret → PVC → StatefulSet → Services
            Poll readiness → status: running
            Fire webhook: instance.running
```

---

## Repository Structure

```
.
├── api/
│   ├── main.py                # App factory, lifespan, scheduler init
│   ├── config.py              # Settings via env vars (pydantic-settings)
│   ├── dependencies.py        # JWT auth FastAPI dependency
│   ├── auth/                  # Register, login, JWT
│   ├── instances/             # CRUD, provisioning, scale-to-zero, replicas, PITR
│   ├── admin/                 # Admin panel (stats, user mgmt, billing trigger)
│   ├── billing/               # Usage queries, monthly summaries
│   ├── metering/              # APScheduler: collect_usage, aggregate_billing
│   ├── webhooks/              # Endpoint management, HMAC dispatch, retry
│   ├── k8s/
│   │   ├── client.py          # K8s client (in-cluster / kubeconfig)
│   │   ├── manifests.py       # Pure-Python K8s resource builders
│   │   └── provisioner.py     # Namespace → Secret → PVC → StatefulSet → Services
│   └── db/
│       ├── models/            # User, Instance, UsageRecord, BillingSummary, AuditLog
│       │                      # WebhookEndpoint, WebhookDelivery, ReadReplica, Backup
│       └── migrations/        # Alembic async migrations
├── frontend/                  # Next.js 14 dashboard (static export)
├── k8s/
│   ├── namespace.yaml         # arc-system namespace
│   ├── storageclass.yaml      # gp3 default StorageClass
│   ├── metrics-server.yaml    # metrics-server v0.7.1
│   ├── migration-job.yaml     # One-off Alembic migration Job
│   ├── api-deployment.yaml    # Deployment + HPA + PDB + LoadBalancer Service
│   └── rbac.yaml              # ClusterRole + ClusterRoleBinding for arc-api SA
├── terraform/
│   ├── main.tf                # Root module (VPC + EKS + RDS + ECR)
│   ├── terraform.tfvars       # Variable values
│   ├── versions.tf            # S3 backend, provider versions
│   └── modules/
│       ├── vpc/               # VPC, subnets (3 AZ), NAT gateway
│       ├── eks/               # EKS cluster, managed node group, addons
│       └── rds/               # RDS PostgreSQL, parameter group, subnet group
├── .github/workflows/
│   └── deploy.yml             # CI: test → build → migrate → deploy
├── Dockerfile                 # Multi-stage: Node 20 + Python 3.12
├── pytest.ini
└── requirements.txt
```

---

## Deployment Guide

### Prerequisites
- AWS account · IAM user with AdministratorAccess
- Terraform ≥ 1.6
- AWS CLI, kubectl, Docker, GitHub CLI (`gh`)

### Step 1 — Bootstrap Terraform state backend
```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws s3 mb s3://arc-tfstate-${ACCOUNT_ID} --region us-east-1

aws dynamodb create-table \
  --table-name terraform-state-lock \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

### Step 2 — Provision AWS infrastructure
```bash
cd terraform
terraform init
terraform apply -auto-approve
```
Creates: VPC (3 AZ) · EKS cluster · managed node group · RDS PostgreSQL 16 · ECR repository

### Step 3 — Connect kubectl
```bash
aws eks update-kubeconfig --region us-east-1 --name arc-cluster
```

### Step 4 — Apply base Kubernetes resources
```bash
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/storageclass.yaml
kubectl apply -f k8s/metrics-server.yaml
kubectl apply -f k8s/rbac.yaml
kubectl apply -f k8s/api-deployment.yaml
```

### Step 5 — Create the API secret
```bash
# Get RDS endpoint from terraform output
RDS=$(cd terraform && terraform output -raw rds_endpoint)

kubectl delete secret arc-api-env -n arc-system --ignore-not-found
kubectl create secret generic arc-api-env -n arc-system \
  --from-literal=DATABASE_URL="postgresql+asyncpg://arcadmin:<password>@${RDS}/arc_control" \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=ENVIRONMENT="prod" \
  --from-literal=STORAGE_CLASS="gp3"
```

### Step 6 — Add GitHub secrets and trigger CI/CD
```bash
gh secret set AWS_ACCESS_KEY_ID
gh secret set AWS_SECRET_ACCESS_KEY
gh workflow run deploy.yml
```

The pipeline will: run tests → build Docker image → push to ECR → run Alembic migrations → rolling deploy to EKS.

### Step 7 — Get your endpoint
```bash
kubectl get svc arc-api -n arc-system \
  -o jsonpath='{.status.loadBalancer.ingress[0].hostname}'
```

---

## API Reference

Full interactive docs at `http://<endpoint>/docs`

| Method | Path | Description |
|---|---|---|
| POST | `/auth/register` | Create account |
| POST | `/auth/login` | Get JWT token |
| GET | `/instances` | List instances |
| POST | `/instances` | Create instance (202 async) |
| GET | `/instances/{id}` | Instance detail + connection string |
| DELETE | `/instances/{id}` | Delete instance (202 async) |
| POST | `/instances/{id}/suspend` | Scale to zero |
| POST | `/instances/{id}/resume` | Resume from zero |
| POST | `/instances/{id}/credentials/rotate` | Rotate password |
| GET | `/instances/{id}/backups` | List backups |
| POST | `/instances/{id}/backups` | Create backup |
| POST | `/instances/{id}/backups/{bid}/restore` | Point-in-time restore |
| GET | `/instances/{id}/replicas` | List read replicas |
| POST | `/instances/{id}/replicas` | Add read replica |
| DELETE | `/instances/{id}/replicas/{rid}` | Remove read replica |
| GET | `/billing/usage` | CPU/memory usage metrics |
| GET | `/billing/summary` | Monthly cost summary |
| GET | `/webhooks/endpoints` | List webhook endpoints |
| POST | `/webhooks/endpoints` | Register endpoint |
| DELETE | `/webhooks/endpoints/{id}` | Remove endpoint |
| GET | `/admin/stats` | Platform stats (admin only) |
| GET | `/admin/users` | All users (admin only) |
| GET | `/admin/instances` | All instances (admin only) |
| GET | `/health` | Health check |

---

## Running Tests

```bash
# Requires a local PostgreSQL instance or the CI postgres service
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/arc_test"

pytest -x -q
```

Tests use a real PostgreSQL database (no mocks for the DB layer) and mock the Kubernetes client so no cluster is needed.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | Control-plane DB connection string (asyncpg) |
| `SECRET_KEY` | — | JWT signing secret (32-byte hex) |
| `JWT_EXPIRE_MINUTES` | `60` | Access token lifetime |
| `K8S_IN_CLUSTER` | `false` | `true` when running inside a pod |
| `KUBECONFIG_PATH` | `~/.kube/config` | Path to kubeconfig (local dev) |
| `ENVIRONMENT` | `dev` | `dev` = NodePort · `prod` = LoadBalancer |
| `STORAGE_CLASS` | `standard` | `standard` (minikube) · `gp3` (EKS) |
| `METERING_INTERVAL_SECS` | `60` | Metrics collection interval |
| `SCALE_TO_ZERO_ENABLED` | `false` | Enable idle instance suspension |

---

## Author

**Navneet Shahi**

Built end-to-end — API design, Kubernetes operator logic, Terraform infrastructure, CI/CD pipeline, and Next.js dashboard. Deployed live on AWS EKS.

---

## License

MIT
