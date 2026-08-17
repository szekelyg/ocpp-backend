"""add is_published to charge_points

Új töltő a BootNotificationből publikálatlanul jön létre: addig nem jelenik meg
az éles appban / OCPI-ban, amíg admin be nem konfigurálta (helyszín, koordináta,
csatlakozó típus, teljesítmény). A migráció a MEGLÉVŐ sorokat publikáltra állítja,
hogy a deploy pillanatában semmi ne tűnjön el a térképről.

Revision ID: f1a2b3c4d5e6
Revises: c1b2c3d4e5f6
Create Date: 2026-08-17
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "c1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "charge_points",
        sa.Column(
            "is_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # A már élő töltők maradjanak láthatóak.
    op.execute("UPDATE charge_points SET is_published = true")
    op.create_index("ix_charge_points_is_published", "charge_points", ["is_published"])


def downgrade() -> None:
    op.drop_index("ix_charge_points_is_published", table_name="charge_points")
    op.drop_column("charge_points", "is_published")
