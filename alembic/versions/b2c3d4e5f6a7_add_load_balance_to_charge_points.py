"""charge_points: terheléselosztás (load_group, load_group_max_a, max_current_a)

Revision ID: b2c3d4e5f6a7
Revises: e5c1a7b3d9f2
Create Date: 2026-09-23 17:00:00.000000

Additív, három nullable oszlop. Lásd app/services/load_balance.py.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "e5c1a7b3d9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("charge_points", sa.Column("load_group", sa.String(64), nullable=True))
    op.add_column("charge_points", sa.Column("load_group_max_a", sa.Integer(), nullable=True))
    op.add_column("charge_points", sa.Column("max_current_a", sa.Integer(), nullable=True))
    op.create_index("ix_charge_points_load_group", "charge_points", ["load_group"])


def downgrade() -> None:
    op.drop_index("ix_charge_points_load_group", table_name="charge_points")
    op.drop_column("charge_points", "max_current_a")
    op.drop_column("charge_points", "load_group_max_a")
    op.drop_column("charge_points", "load_group")
