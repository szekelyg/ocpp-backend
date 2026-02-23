"""add meter_start_wh and meter_stop_wh to charge_sessions

Revision ID: 50dda8dce6d6
Revises: 3822dca99ff6
Create Date: 2026-02-23 12:20:23.364883

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50dda8dce6d6'
down_revision: Union[str, Sequence[str], None] = '3822dca99ff6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "charge_sessions",
        sa.Column("meter_start_wh", sa.Float(), nullable=True),
    )
    op.add_column(
        "charge_sessions",
        sa.Column("meter_stop_wh", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("charge_sessions", "meter_stop_wh")
    op.drop_column("charge_sessions", "meter_start_wh")
