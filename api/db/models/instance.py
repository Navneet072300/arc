import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db.base import Base


class Instance(Base):
    __tablename__ = "instances"
    __table_args__ = (
        Index("ix_instances_user_id", "user_id"),
        Index("ix_instances_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="provisioning")
    k8s_namespace: Mapped[str] = mapped_column(Text, nullable=False)
    k8s_statefulset: Mapped[str] = mapped_column(Text, nullable=False)
    pg_version: Mapped[str] = mapped_column(Text, default="16")
    cpu_request: Mapped[str] = mapped_column(Text, default="250m")
    cpu_limit: Mapped[str] = mapped_column(Text, default="500m")
    mem_request: Mapped[str] = mapped_column(Text, default="256Mi")
    mem_limit: Mapped[str] = mapped_column(Text, default="512Mi")
    storage_size: Mapped[str] = mapped_column(Text, default="5Gi")
    pg_db_name: Mapped[str] = mapped_column(Text, default="postgres")
    pg_username: Mapped[str] = mapped_column(Text, nullable=False)
    k8s_secret_name: Mapped[str] = mapped_column(Text, nullable=False)
    external_host: Mapped[str | None] = mapped_column(Text)
    external_port: Mapped[int | None] = mapped_column(Integer)
    # PgBouncer connection pooling
    pool_mode: Mapped[str] = mapped_column(Text, default="transaction")   # transaction | session | statement
    pool_size: Mapped[int] = mapped_column(Integer, default=20)
    max_client_conn: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="instances")  # noqa: F821
    usage_records: Mapped[list["UsageRecord"]] = relationship(  # noqa: F821
        "UsageRecord", back_populates="instance", lazy="select"
    )
