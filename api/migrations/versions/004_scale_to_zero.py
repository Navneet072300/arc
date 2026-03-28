"""add scale-to-zero columns to instances

Revision ID: 004
Revises: 003
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("instances", sa.Column("auto_suspend", sa.Boolean, server_default="true", nullable=False))
    op.add_column("instances", sa.Column("idle_timeout_minutes", sa.Integer, server_default="30", nullable=False))
    op.add_column("instances", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("instances", "suspended_at")
    op.drop_column("instances", "idle_timeout_minutes")
    op.drop_column("instances", "auto_suspend")
