import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.admin.router import router as admin_router
from api.auth.router import router as auth_router
from api.billing.router import router as billing_router
from api.config import settings
from api.db.session import engine
from api.instances.router import router as instances_router
from api.k8s.client import get_k8s_client
from api.metering.collector import aggregate_billing, check_idle_instances, collect_usage
from api.users.router import router as users_router
from api.webhooks.router import router as webhooks_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify DB connection
    async with engine.connect():
        pass
    logger.info("Database connection OK")

    # Verify K8s connection
    try:
        from kubernetes import client

        k8s = get_k8s_client()
        v1 = client.CoreV1Api(k8s)
        v1.list_namespace(limit=1)
        logger.info("Kubernetes connection OK")
    except Exception as exc:
        logger.warning("Kubernetes connection failed (will retry on use): %s", exc)

    # Start metering scheduler
    scheduler.add_job(collect_usage, "interval", seconds=settings.METERING_INTERVAL_SECS, id="collect_usage")
    scheduler.add_job(aggregate_billing, "cron", hour=2, minute=0, id="aggregate_billing")
    scheduler.add_job(
        check_idle_instances,
        "interval",
        seconds=settings.SCALE_TO_ZERO_CHECK_INTERVAL_SECS,
        id="check_idle_instances",
    )
    scheduler.start()
    logger.info("Metering scheduler started (interval=%ss)", settings.METERING_INTERVAL_SECS)

    yield

    scheduler.shutdown(wait=False)
    await engine.dispose()


app = FastAPI(
    title="Serverless PostgreSQL Platform",
    description="Deploy and manage PostgreSQL instances on Kubernetes",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(instances_router)
app.include_router(billing_router)
app.include_router(webhooks_router)

# Dashboard static files
try:
    app.mount("/ui", StaticFiles(directory="dashboard", html=True), name="dashboard")
except RuntimeError:
    logger.warning("Dashboard directory not found, skipping static files mount")


@app.get("/health", tags=["health"])
async def health():
    db_ok = False
    k8s_ok = False

    try:
        async with engine.connect():
            db_ok = True
    except Exception:
        pass

    try:
        from kubernetes import client

        k8s = get_k8s_client()
        v1 = client.CoreV1Api(k8s)
        v1.list_namespace(limit=1)
        k8s_ok = True
    except Exception:
        pass

    return {
        "status": "ok" if (db_ok and k8s_ok) else "degraded",
        "db": "ok" if db_ok else "error",
        "k8s": "ok" if k8s_ok else "error",
    }
