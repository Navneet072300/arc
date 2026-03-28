"""add read_replicas table and replication_password to instances

Revision ID: 005
Revises: 004
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "read_replicas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text, unique=True, nullable=False),
        sa.Column("k8s_statefulset", sa.Text, nullable=False),
        sa.Column("k8s_service", sa.Text, nullable=False),
        sa.Column("status", sa.Text, server_default="provisioning", nullable=False),
        sa.Column("external_host", sa.Text, nullable=True),
        sa.Column("external_port", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_read_replicas_instance_id", "read_replicas", ["instance_id"])


def downgrade() -> None:
    op.drop_index("ix_read_replicas_instance_id", table_name="read_replicas")
    op.drop_table("read_replicas")
