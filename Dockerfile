# ── Stage 1: Build Next.js frontend ──────────────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline

COPY frontend/ .
RUN npm run build
# outputs to /frontend/out  (next.config: output: "export")


# ── Stage 2: Python API ───────────────────────────────────────────────────────
FROM python:3.12-slim AS api

# Install OS deps needed by psycopg2 / cryptography
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY api/       ./api/
COPY alembic.ini ./

# Copy built frontend into the path the API serves (/ui → StaticFiles)
COPY --from=frontend-builder /frontend/out ./dashboard/

# Non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Use multiple uvicorn workers in production; override with --workers 1 for dev
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
