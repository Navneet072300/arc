"""
Webhook delivery engine.
- Signs payloads with HMAC-SHA256 using the endpoint's secret
- Retries up to 3 times with exponential backoff (5s, 25s, 125s)
- Records every attempt in webhook_deliveries
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.webhook import WebhookDelivery, WebhookEndpoint
from api.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
TIMEOUT_SECS = 10
BACKOFF = [0, 5, 25, 125]  # seconds before each retry

ALL_EVENTS = [
    "instance.provisioning",
    "instance.running",
    "instance.error",
    "instance.deleted",
    "credentials.rotated",
]


def _sign_payload(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def dispatch_event(
    event: str,
    payload: dict,
    user_id: uuid.UUID,
) -> None:
    """
    Find all active endpoints for this user that subscribed to this event,
    create delivery records, and fire them in the background.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(WebhookEndpoint).where(
                WebhookEndpoint.user_id == user_id,
                WebhookEndpoint.is_active.is_(True),
            )
        )
        endpoints = result.scalars().all()

        deliveries = []
        for ep in endpoints:
            if event in ep.events or "*" in ep.events:
                delivery = WebhookDelivery(
                    endpoint_id=ep.id,
                    event=event,
                    payload=payload,
                    status="pending",
                )
                db.add(delivery)
                deliveries.append((ep, delivery))

        await db.commit()
        for ep, delivery in deliveries:
            await db.refresh(delivery)

    # Fire deliveries concurrently in background
    for ep, delivery in deliveries:
        asyncio.create_task(_deliver_with_retry(ep.id, delivery.id, ep.url, ep.secret, event, payload))


async def _deliver_with_retry(
    endpoint_id: uuid.UUID,
    delivery_id: uuid.UUID,
    url: str,
    secret: str,
    event: str,
    payload: dict,
) -> None:
    body = json.dumps({
        "event": event,
        "timestamp": datetime.now(UTC).isoformat(),
        **payload,
    }).encode()
    signature = _sign_payload(secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-Arc-Event": event,
        "X-Arc-Signature": signature,
        "User-Agent": "Arc-Webhooks/1.0",
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        if attempt > 1:
            await asyncio.sleep(BACKOFF[attempt - 1])

        status_code = None
        response_body = None
        success = False

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECS) as client:
                resp = await client.post(url, content=body, headers=headers)
                status_code = resp.status_code
                response_body = resp.text[:500]
                success = 200 <= status_code < 300
        except Exception as exc:
            response_body = str(exc)[:500]
            logger.warning("Webhook delivery attempt %d failed for %s: %s", attempt, url, exc)

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id))
            delivery = result.scalar_one_or_none()
            if delivery:
                delivery.attempts = attempt
                delivery.response_code = status_code
                delivery.response_body = response_body
                delivery.last_attempt_at = datetime.now(UTC)
                delivery.status = "success" if success else ("failed" if attempt == MAX_ATTEMPTS else "pending")
                await db.commit()

        if success:
            logger.info("Webhook delivered: event=%s url=%s status=%s", event, url, status_code)
            return

    logger.error("Webhook failed after %d attempts: event=%s url=%s", MAX_ATTEMPTS, event, url)


async def get_endpoints(db: AsyncSession, user_id: uuid.UUID) -> list[WebhookEndpoint]:
    result = await db.execute(
        select(WebhookEndpoint).where(WebhookEndpoint.user_id == user_id).order_by(WebhookEndpoint.created_at.desc())
    )
    return list(result.scalars())


async def get_deliveries(db: AsyncSession, endpoint_id: uuid.UUID, limit: int = 20) -> list[WebhookDelivery]:
    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.endpoint_id == endpoint_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())
