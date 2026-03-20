"""add billing fields to charging_intents

Revision ID: b9f3a21c7e04
Revises: a1b2c3d4e5f6
Create Date: 2026-03-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b9f3a21c7e04'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Felhasználó által megadott mezők (intent létrehozáskor)
    op.add_column('charging_intents', sa.Column('billing_type', sa.String(16), nullable=True))       # "personal" | "business"
    op.add_column('charging_intents', sa.Column('billing_company', sa.String(255), nullable=True))   # cégnév (céges)
    op.add_column('charging_intents', sa.Column('billing_tax_number', sa.String(64), nullable=True)) # adószám (céges)

    # Stripe customer_details (webhook után töltjük ki)
    op.add_column('charging_intents', sa.Column('billing_name', sa.String(255), nullable=True))    # kártyabirtokos neve
    op.add_column('charging_intents', sa.Column('billing_zip', sa.String(16), nullable=True))
    op.add_column('charging_intents', sa.Column('billing_city', sa.String(128), nullable=True))
    op.add_column('charging_intents', sa.Column('billing_country', sa.String(4), nullable=True))


def downgrade() -> None:
    op.drop_column('charging_intents', 'billing_country')
    op.drop_column('charging_intents', 'billing_city')
    op.drop_column('charging_intents', 'billing_zip')
    op.drop_column('charging_intents', 'billing_name')
    op.drop_column('charging_intents', 'billing_tax_number')
    op.drop_column('charging_intents', 'billing_company')
    op.drop_column('charging_intents', 'billing_type')
