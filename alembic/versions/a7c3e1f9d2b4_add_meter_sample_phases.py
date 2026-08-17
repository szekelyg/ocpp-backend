"""add phases (per-phase power/current) to meter_samples

Revision ID: a7c3e1f9d2b4
Revises: f5a1c2d3e4b6
Create Date: 2026-07-01 16:35:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7c3e1f9d2b4"
down_revision: Union[str, Sequence[str], None] = "f5a1c2d3e4b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("meter_samples", sa.Column("phases", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("meter_samples", "phases")
