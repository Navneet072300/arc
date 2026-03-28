import uuid
from datetime import datetime

from pydantic import BaseModel, HttpUrl


class CreateWebhookRequest(BaseModel):
    url: HttpUrl
    events: list[str]
    secret: str | None = None  # auto-generated if not provided

    model_config = {"from_attributes": True}


class WebhookEndpointResponse(BaseModel):
    id: uuid.UUID
    url: str
    events: list[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class WebhookDeliveryResponse(BaseModel):
    id: uuid.UUID
    event: str
    status: str
    attempts: int
    response_code: int | None
    response_body: str | None
    last_attempt_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
