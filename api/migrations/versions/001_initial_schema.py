"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text, unique=True, nullable=False),
        sa.Column("hashed_password", sa.Text, nullable=False),
        sa.Column("full_name", sa.Text),
        sa.Column("is_active", sa.Boolean, default=True, server_default="true"),
        sa.Column("is_admin", sa.Boolean, default=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(255), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean, default=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, unique=True, nullable=False),
        sa.Column("status", sa.Text, default="provisioning", server_default="provisioning"),
        sa.Column("k8s_namespace", sa.Text, nullable=False),
        sa.Column("k8s_statefulset", sa.Text, nullable=False),
        sa.Column("pg_version", sa.Text, default="16", server_default="16"),
        sa.Column("cpu_request", sa.Text, default="250m", server_default="250m"),
        sa.Column("cpu_limit", sa.Text, default="500m", server_default="500m"),
        sa.Column("mem_request", sa.Text, default="256Mi", server_default="256Mi"),
        sa.Column("mem_limit", sa.Text, default="512Mi", server_default="512Mi"),
        sa.Column("storage_size", sa.Text, default="5Gi", server_default="5Gi"),
        sa.Column("pg_db_name", sa.Text, default="postgres", server_default="postgres"),
        sa.Column("pg_username", sa.Text, nullable=False),
        sa.Column("k8s_secret_name", sa.Text, nullable=False),
        sa.Column("external_host", sa.Text),
        sa.Column("external_port", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_instances_user_id", "instances", ["user_id"])
    op.create_index("ix_instances_status", "instances", ["status"])

    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("cpu_millicores", sa.Numeric(12, 4)),
        sa.Column("mem_bytes", sa.BigInteger),
        sa.Column("storage_bytes", sa.BigInteger),
        sa.Column("interval_secs", sa.Integer, default=60, server_default="60"),
    )
    op.create_index("ix_usage_records_instance_recorded", "usage_records", ["instance_id", "recorded_at"])

    op.create_table(
        "billing_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("instances.id"), nullable=False),
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column("cpu_core_hours", sa.Numeric(14, 6)),
        sa.Column("mem_gb_hours", sa.Numeric(14, 6)),
        sa.Column("storage_gb_days", sa.Numeric(14, 6)),
        sa.Column("amount_usd", sa.Numeric(10, 4)),
        sa.Column("status", sa.Text, default="draft", server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("instance_id", "period_start", name="uq_billing_instance_period"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("details", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_user_created", "audit_logs", ["user_id", "created_at"])
    op.create_index("ix_audit_logs_resource_id", "audit_logs", ["resource_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("billing_summaries")
    op.drop_table("usage_records")
    op.drop_table("instances")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
