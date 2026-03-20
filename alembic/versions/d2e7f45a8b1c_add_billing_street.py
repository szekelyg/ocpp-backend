"""add billing_street to charging_intents

Revision ID: d2e7f45a8b1c
Revises: c4d8e92f1a3b
Create Date: 2026-03-20 12:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd2e7f45a8b1c'
down_revision: Union[str, Sequence[str], None] = 'c4d8e92f1a3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('charging_intents', sa.Column('billing_street', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('charging_intents', 'billing_street')
