"""add stripe_payment_intent_id to charging_intents

Revision ID: c4d8e92f1a3b
Revises: b9f3a21c7e04
Create Date: 2026-03-20 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d8e92f1a3b'
down_revision: Union[str, Sequence[str], None] = 'b9f3a21c7e04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'charging_intents',
        sa.Column('stripe_payment_intent_id', sa.String(255), nullable=True, index=True),
    )
    op.create_index(
        'ix_charging_intents_stripe_pi_id',
        'charging_intents',
        ['stripe_payment_intent_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_charging_intents_stripe_pi_id', table_name='charging_intents')
    op.drop_column('charging_intents', 'stripe_payment_intent_id')
