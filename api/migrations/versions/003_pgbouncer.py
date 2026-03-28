"""add pgbouncer pool columns to instances

Revision ID: 003
Revises: 002
Create Date: 2026-03-28
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("instances", sa.Column("pool_mode", sa.Text, server_default="transaction", nullable=False))
    op.add_column("instances", sa.Column("pool_size", sa.Integer, server_default="20", nullable=False))
    op.add_column("instances", sa.Column("max_client_conn", sa.Integer, server_default="100", nullable=False))


def downgrade() -> None:
    op.drop_column("instances", "max_client_conn")
    op.drop_column("instances", "pool_size")
    op.drop_column("instances", "pool_mode")
