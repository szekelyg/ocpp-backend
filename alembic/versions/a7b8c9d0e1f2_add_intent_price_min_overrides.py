"""add per-intent price/min overrides (admin test pricing)

Revision ID: a7b8c9d0e1f2
Revises: e3f1a9b2c5d7
Create Date: 2026-06-15 00:00:00.000000

Per-intent árazási felülírás. NULL = a globális env értéket (OCPP_PRICE_HUF_PER_KWH,
STRIPE_MIN_HUF) használja. Az admin teszt-töltés tölti ki ezeket (5 Ft/kWh, 200 Ft),
így a publikus árazás változatlan marad.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "e3f1a9b2c5d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("charging_intents", sa.Column("price_huf_per_kwh", sa.Float(), nullable=True))
    op.add_column("charging_intents", sa.Column("min_charge_huf", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("charging_intents", "min_charge_huf")
    op.drop_column("charging_intents", "price_huf_per_kwh")
