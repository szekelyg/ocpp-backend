"""add indexes and unique constraint on intent_id

Revision ID: a1b2c3d4e5f6
Revises: 50dda8dce6d6
Create Date: 2026-03-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '81720a5f8301'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Index charge_sessions.charge_point_id (frequently queried)
    op.create_index(
        'ix_charge_sessions_charge_point_id',
        'charge_sessions',
        ['charge_point_id'],
    )

    # Unique constraint + index on charge_sessions.intent_id
    # (egy intenthez csak egy session lehet – race condition védelem)
    op.create_index(
        'ix_charge_sessions_intent_id',
        'charge_sessions',
        ['intent_id'],
        unique=True,
        postgresql_where=sa.text('intent_id IS NOT NULL'),
    )

    # Index meter_samples.session_id (frequently queried for live data)
    op.create_index(
        'ix_meter_samples_session_id',
        'meter_samples',
        ['session_id'],
    )

    # Index meter_samples.charge_point_id
    op.create_index(
        'ix_meter_samples_charge_point_id',
        'meter_samples',
        ['charge_point_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_meter_samples_charge_point_id', table_name='meter_samples')
    op.drop_index('ix_meter_samples_session_id', table_name='meter_samples')
    op.drop_index('ix_charge_sessions_intent_id', table_name='charge_sessions')
    op.drop_index('ix_charge_sessions_charge_point_id', table_name='charge_sessions')
