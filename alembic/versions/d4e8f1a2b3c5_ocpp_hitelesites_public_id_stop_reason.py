"""charge_points: public_id + OCPP Basic Auth mezők; charge_sessions: stop_reason

Revision ID: d4e8f1a2b3c5
Revises: b2c3d4e5f6a7
Create Date: 2026-10-14 10:00:00.000000

Additív:
- charge_points.public_id: stabil, pszeudonim azonosító (UUID) a publikus API-hoz – a
  publikus töltőlista ezt adja ki az ocpp_id és a sorszámos id helyett. Meglévő sorokra
  visszatöltve, utána NOT NULL + egyedi index.
- charge_points.ocpp_auth_*: OCPP 1.6 Security Profile 2 (TLS + HTTP Basic Auth) előkészítés –
  a töltőnkénti kulcs hash-e (soha nem a kulcs maga), és az utolsó kapcsolódás hitelesítési
  eredménye / sémája (ws vagy wss). Lásd docs/OCPP-HITELESITES.md.
- charge_sessions.stop_reason: a StopTransaction "reason" mezője (MEKH havi jelentés).
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e8f1a2b3c5"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("charge_points", sa.Column("public_id", sa.String(36), nullable=True))
    conn = op.get_bind()
    ids = [r[0] for r in conn.execute(sa.text("SELECT id FROM charge_points WHERE public_id IS NULL"))]
    for cp_id in ids:
        conn.execute(
            sa.text("UPDATE charge_points SET public_id = :p WHERE id = :i"),
            {"p": str(uuid.uuid4()), "i": cp_id},
        )
    op.alter_column("charge_points", "public_id", existing_type=sa.String(36), nullable=False)
    op.create_index("ix_charge_points_public_id", "charge_points", ["public_id"], unique=True)

    op.add_column("charge_points", sa.Column("ocpp_auth_key_hash", sa.String(255), nullable=True))
    op.add_column("charge_points", sa.Column("ocpp_auth_key_set_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("charge_points", sa.Column("ocpp_auth_last_result", sa.String(16), nullable=True))
    op.add_column("charge_points", sa.Column("ocpp_auth_last_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("charge_points", sa.Column("ocpp_last_scheme", sa.String(8), nullable=True))

    op.add_column("charge_sessions", sa.Column("stop_reason", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("charge_sessions", "stop_reason")
    op.drop_column("charge_points", "ocpp_last_scheme")
    op.drop_column("charge_points", "ocpp_auth_last_at")
    op.drop_column("charge_points", "ocpp_auth_last_result")
    op.drop_column("charge_points", "ocpp_auth_key_set_at")
    op.drop_column("charge_points", "ocpp_auth_key_hash")
    op.drop_index("ix_charge_points_public_id", table_name="charge_points")
    op.drop_column("charge_points", "public_id")
