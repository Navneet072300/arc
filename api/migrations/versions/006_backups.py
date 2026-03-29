"""add backups table

Revision ID: 006
Revises: 005
Create Date: 2026-03-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text, unique=True, nullable=False),
        sa.Column("status", sa.Text, server_default="creating", nullable=False),
        sa.Column("k8s_job", sa.Text, nullable=False),
        sa.Column("backup_pvc", sa.Text, nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_backups_instance_id", "backups", ["instance_id"])


def downgrade() -> None:
    op.drop_index("ix_backups_instance_id", table_name="backups")
    op.drop_table("backups")
