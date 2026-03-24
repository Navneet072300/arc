import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class CreateInstanceRequest(BaseModel):
    name: str
    pg_version: str = "16"
    cpu_request: str = "250m"
    cpu_limit: str = "500m"
    mem_request: str = "256Mi"
    mem_limit: str = "512Mi"
    storage_size: str = "5Gi"
    pg_db_name: str = "postgres"
    pg_username: str = "pguser"

    @field_validator("name")
    @classmethod
    def name_must_be_slug_safe(cls, v: str) -> str:
        import re
        if not re.match(r"^[a-z0-9][a-z0-9\-]{0,30}[a-z0-9]$", v):
            raise ValueError("name must be lowercase alphanumeric and hyphens, 2-32 chars")
        return v


class InstanceResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    pg_version: str
    pg_db_name: str
    pg_username: str
    external_host: str | None
    external_port: int | None
    cpu_request: str
    mem_request: str
    storage_size: str
    created_at: datetime

    model_config = {"from_attributes": True}


class InstanceDetailResponse(InstanceResponse):
    connection_string: str | None = None


class InstanceCreatedResponse(InstanceDetailResponse):
    password: str | None = None  # Only returned once at creation


class CredentialsRotateResponse(BaseModel):
    connection_string: str
    password: str
    username: str
    host: str | None
    port: int | None
    database: str


class InstanceStatusResponse(BaseModel):
    id: uuid.UUID
    status: str
    external_host: str | None
    external_port: int | None
