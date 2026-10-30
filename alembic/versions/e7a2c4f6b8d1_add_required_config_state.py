"""charge_points.required_config_state: a kötelező töltő-beállítások utolsó ellenőrzése

Revision ID: e7a2c4f6b8d1
Revises: d4e8f1a2b3c5
Create Date: 2026-10-30 12:00:00.000000

Additív, nullable JSON-oszlop (app/ocpp/required_config.py): a ConnectionTimeOut és az
offline töltést tiltó kulcsok eredménye töltőnként (ok / eltér / elutasítva), az admin mutatja.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7a2c4f6b8d1"
down_revision: Union[str, Sequence[str], None] = "d4e8f1a2b3c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("charge_points", sa.Column("required_config_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("charge_points", "required_config_state")
