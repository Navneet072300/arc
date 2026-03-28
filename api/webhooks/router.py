import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.models.user import User
from api.db.models.webhook import WebhookDelivery, WebhookEndpoint
from api.db.session import get_db
from api.dependencies import get_current_user
from api.webhooks import service
from api.webhooks.schemas import (
    CreateWebhookRequest,
    WebhookDeliveryResponse,
    WebhookEndpointResponse,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

VALID_EVENTS = set(service.ALL_EVENTS) | {"*"}


@router.get("", response_model=list[WebhookEndpointResponse])
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await service.get_endpoints(db, current_user.id)


@router.post("", response_model=WebhookEndpointResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: CreateWebhookRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    invalid = [e for e in body.events if e not in VALID_EVENTS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid events: {invalid}. Valid: {sorted(VALID_EVENTS)}")

    endpoint = WebhookEndpoint(
        user_id=current_user.id,
        url=str(body.url),
        secret=body.secret or secrets.token_hex(32),
        events=body.events,
    )
    db.add(endpoint)
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


@router.get("/{endpoint_id}", response_model=WebhookEndpointResponse)
async def get_webhook(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ep = await _get_owned(db, endpoint_id, current_user.id)
    return ep


@router.patch("/{endpoint_id}", response_model=WebhookEndpointResponse)
async def update_webhook(
    endpoint_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ep = await _get_owned(db, endpoint_id, current_user.id)
    if "is_active" in body:
        ep.is_active = bool(body["is_active"])
    if "events" in body:
        invalid = [e for e in body["events"] if e not in VALID_EVENTS]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid events: {invalid}")
        ep.events = body["events"]
    await db.commit()
    await db.refresh(ep)
    return ep


@router.delete("/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ep = await _get_owned(db, endpoint_id, current_user.id)
    await db.delete(ep)
    await db.commit()


@router.get("/{endpoint_id}/deliveries", response_model=list[WebhookDeliveryResponse])
async def list_deliveries(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _get_owned(db, endpoint_id, current_user.id)
    return await service.get_deliveries(db, endpoint_id)


@router.post("/{endpoint_id}/test", status_code=status.HTTP_202_ACCEPTED)
async def test_webhook(
    endpoint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send a test ping event to the endpoint."""
    ep = await _get_owned(db, endpoint_id, current_user.id)
    await service.dispatch_event(
        event="webhook.test",
        payload={"message": "This is a test event from Arc", "endpoint_id": str(ep.id)},
        user_id=current_user.id,
    )
    return {"detail": "Test event dispatched"}


async def _get_owned(db: AsyncSession, endpoint_id: uuid.UUID, user_id: uuid.UUID) -> WebhookEndpoint:
    result = await db.execute(
        select(WebhookEndpoint).where(WebhookEndpoint.id == endpoint_id, WebhookEndpoint.user_id == user_id)
    )
    ep = result.scalar_one_or_none()
    if not ep:
        raise HTTPException(status_code=404, detail="Webhook endpoint not found")
    return ep
