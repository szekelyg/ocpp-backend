"""fix charging_intents currency default

Revision ID: 81720a5f8301
Revises: 
Create Date: 2026-02-24 13:12:01.105507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision = "81720a5f8301"
down_revision = "52a6a0de7c0d"
branch_labels = None
depends_on = None

def upgrade() -> None:
    # 1) régi sorok javítása
    op.execute("UPDATE charging_intents SET currency='huf' WHERE currency IS NULL")

    # 2) DB default + NOT NULL biztosítás
    op.alter_column(
        "charging_intents",
        "currency",
        existing_type=sa.String(length=8),
        nullable=False,
        server_default=sa.text("'huf'"),
    )

def downgrade() -> None:
    op.alter_column(
        "charging_intents",
        "currency",
        existing_type=sa.String(length=8),
        nullable=True,
        server_default=None,
    )
