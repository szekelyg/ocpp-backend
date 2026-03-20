"""add invoice_number to charge_sessions

Revision ID: 98abe267fa49
Revises: d2e7f45a8b1c
Create Date: 2026-03-20 13:00:05.080689

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '98abe267fa49'
down_revision: Union[str, Sequence[str], None] = 'd2e7f45a8b1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("charge_sessions", sa.Column("invoice_number", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("charge_sessions", "invoice_number")
