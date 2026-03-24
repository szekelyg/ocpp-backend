"""add connector_type and max_power_kw to charge_points

Revision ID: e3f1a9b2c5d7
Revises: 98abe267fa49
Create Date: 2026-03-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3f1a9b2c5d7"
down_revision: Union[str, None] = "98abe267fa49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("charge_points", sa.Column("connector_type", sa.String(64), nullable=True))
    op.add_column("charge_points", sa.Column("max_power_kw", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("charge_points", "max_power_kw")
    op.drop_column("charge_points", "connector_type")
