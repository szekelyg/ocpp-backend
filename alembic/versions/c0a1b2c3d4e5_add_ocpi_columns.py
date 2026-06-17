"""add OCPI identity columns to locations, charge_points, charge_sessions

Revision ID: c0a1b2c3d4e5
Revises: a7b8c9d0e1f2
Create Date: 2026-06-17 00:00:00.000000

OCPI 2.2.1 (CPO) identity fields. country_code/party_id/time_zone get a
server_default so existing rows backfill automatically (kept on the column to
match the ORM defaults). ocpi_evse_uid backfills from ocpp_id; the various
ocpi_last_updated columns backfill from updated_at.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c0a1b2c3d4e5"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # locations
    op.add_column("locations", sa.Column("country_code", sa.String(2), nullable=False, server_default="HU"))
    op.add_column("locations", sa.Column("party_id", sa.String(3), nullable=False, server_default="ENF"))
    op.add_column("locations", sa.Column("time_zone", sa.String(64), nullable=False, server_default="Europe/Budapest"))
    op.add_column("locations", sa.Column("ocpi_last_updated", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE locations SET ocpi_last_updated = updated_at WHERE ocpi_last_updated IS NULL")

    # charge_points
    op.add_column("charge_points", sa.Column("ocpi_evse_uid", sa.String(48), nullable=True))
    op.add_column("charge_points", sa.Column("ocpi_last_updated", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE charge_points SET ocpi_evse_uid = ocpp_id WHERE ocpi_evse_uid IS NULL")
    op.execute("UPDATE charge_points SET ocpi_last_updated = updated_at WHERE ocpi_last_updated IS NULL")

    # charge_sessions
    op.add_column("charge_sessions", sa.Column("ocpi_session_id", sa.String(36), nullable=True))
    op.add_column("charge_sessions", sa.Column("ocpi_last_updated", sa.DateTime(timezone=True), nullable=True))
    op.add_column("charge_sessions", sa.Column("ocpi_auth_method", sa.String(16), nullable=True))
    op.add_column("charge_sessions", sa.Column("ocpi_token_uid", sa.String(36), nullable=True))
    op.add_column("charge_sessions", sa.Column("ocpi_country_code", sa.String(2), nullable=True))
    op.add_column("charge_sessions", sa.Column("ocpi_party_id", sa.String(3), nullable=True))
    op.create_index("ix_charge_sessions_ocpi_session_id", "charge_sessions", ["ocpi_session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_charge_sessions_ocpi_session_id", table_name="charge_sessions")
    op.drop_column("charge_sessions", "ocpi_party_id")
    op.drop_column("charge_sessions", "ocpi_country_code")
    op.drop_column("charge_sessions", "ocpi_token_uid")
    op.drop_column("charge_sessions", "ocpi_auth_method")
    op.drop_column("charge_sessions", "ocpi_last_updated")
    op.drop_column("charge_sessions", "ocpi_session_id")

    op.drop_column("charge_points", "ocpi_last_updated")
    op.drop_column("charge_points", "ocpi_evse_uid")

    op.drop_column("locations", "ocpi_last_updated")
    op.drop_column("locations", "time_zone")
    op.drop_column("locations", "party_id")
    op.drop_column("locations", "country_code")
