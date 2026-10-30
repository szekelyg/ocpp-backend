"""charge_sessions.offline_wait_since: kifizetett munkamenet, amely offline töltőre vár

Revision ID: f8b3d1e5a7c9
Revises: e7a2c4f6b8d1
Create Date: 2026-10-30 18:00:00.000000

Additív, nullable oszlop (app/ocpp/handlers/pending_start.py): ha a kifizetett, el nem indult
munkamenet 5 perces ablaka úgy jár le, hogy a töltő offline, nem zárjuk le, hanem a töltő
visszatérésére várunk (legfeljebb 24 óráig a fizetéstől). Meglévő sorokra NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f8b3d1e5a7c9"
down_revision: Union[str, Sequence[str], None] = "e7a2c4f6b8d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("charge_sessions", sa.Column("offline_wait_since", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("charge_sessions", "offline_wait_since")
