"""add OCPI tables (parties, tokens, cdrs, command_results, tariffs)

Revision ID: c1b2c3d4e5f6
Revises: c0a1b2c3d4e5
Create Date: 2026-06-17 00:00:01.000000

New tables for the OCPI 2.2.1 CPO layer: registered roaming partners +
credentials state (ocpi_parties), cached eMSP tokens (ocpi_tokens), immutable
CDR snapshots (ocpi_cdrs), async command audit (ocpi_command_results), and a
thin tariff table (ocpi_tariffs).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c1b2c3d4e5f6"
down_revision: Union[str, None] = "c0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ocpi_parties",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(8), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("party_id", sa.String(3), nullable=False),
        sa.Column("business_name", sa.String(255), nullable=True),
        sa.Column("business_website", sa.String(512), nullable=True),
        sa.Column("business_logo_url", sa.String(512), nullable=True),
        sa.Column("versions_url", sa.String(512), nullable=True),
        sa.Column("version_details_url", sa.String(512), nullable=True),
        sa.Column("endpoints", sa.JSON(), nullable=True),
        sa.Column("token_incoming", sa.String(255), nullable=True),
        sa.Column("token_outgoing", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role", "country_code", "party_id", name="uq_ocpi_party_identity"),
    )
    op.create_index(op.f("ix_ocpi_parties_id"), "ocpi_parties", ["id"], unique=False)
    op.create_index(op.f("ix_ocpi_parties_token_incoming"), "ocpi_parties", ["token_incoming"], unique=False)

    op.create_table(
        "ocpi_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("party_id", sa.String(3), nullable=False),
        sa.Column("uid", sa.String(36), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("contract_id", sa.String(36), nullable=False),
        sa.Column("visual_number", sa.String(64), nullable=True),
        sa.Column("issuer", sa.String(64), nullable=True),
        sa.Column("group_id", sa.String(36), nullable=True),
        sa.Column("valid", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("whitelist", sa.String(16), nullable=False, server_default="NEVER"),
        sa.Column("language", sa.String(2), nullable=True),
        sa.Column("default_profile_type", sa.String(16), nullable=True),
        sa.Column("energy_contract", sa.JSON(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("country_code", "party_id", "uid", "type", name="uq_ocpi_token_identity"),
    )
    op.create_index(op.f("ix_ocpi_tokens_id"), "ocpi_tokens", ["id"], unique=False)
    op.create_index(op.f("ix_ocpi_tokens_uid"), "ocpi_tokens", ["uid"], unique=False)

    op.create_table(
        "ocpi_cdrs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cdr_id", sa.String(39), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("party_id", sa.String(3), nullable=False),
        sa.Column("start_date_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cdr_token", sa.JSON(), nullable=False),
        sa.Column("auth_method", sa.String(16), nullable=False),
        sa.Column("cdr_location", sa.JSON(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
        sa.Column("tariffs", sa.JSON(), nullable=True),
        sa.Column("charging_periods", sa.JSON(), nullable=True),
        sa.Column("total_energy", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_time", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.JSON(), nullable=False),
        sa.Column("invoice_reference_id", sa.String(64), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["session_id"], ["charge_sessions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("cdr_id", name="uq_ocpi_cdr_id"),
    )
    op.create_index(op.f("ix_ocpi_cdrs_id"), "ocpi_cdrs", ["id"], unique=False)
    op.create_index(op.f("ix_ocpi_cdrs_cdr_id"), "ocpi_cdrs", ["cdr_id"], unique=True)
    op.create_index(op.f("ix_ocpi_cdrs_session_id"), "ocpi_cdrs", ["session_id"], unique=False)
    op.create_index(op.f("ix_ocpi_cdrs_last_updated"), "ocpi_cdrs", ["last_updated"], unique=False)

    op.create_table(
        "ocpi_command_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("command", sa.String(24), nullable=False),
        sa.Column("party_country_code", sa.String(2), nullable=True),
        sa.Column("party_party_id", sa.String(3), nullable=True),
        sa.Column("response_url", sa.String(512), nullable=True),
        sa.Column("request_body", sa.JSON(), nullable=True),
        sa.Column("command_response", sa.String(16), nullable=True),
        sa.Column("command_result", sa.String(24), nullable=True),
        sa.Column("charge_point_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("callback_status_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["charge_point_id"], ["charge_points.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["charge_sessions.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_ocpi_command_results_id"), "ocpi_command_results", ["id"], unique=False)

    op.create_table(
        "ocpi_tariffs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tariff_id", sa.String(36), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("party_id", sa.String(3), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="HUF"),
        sa.Column("elements", sa.JSON(), nullable=False),
        sa.Column("min_price", sa.JSON(), nullable=True),
        sa.Column("max_price", sa.JSON(), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tariff_id", name="uq_ocpi_tariff_id"),
    )
    op.create_index(op.f("ix_ocpi_tariffs_id"), "ocpi_tariffs", ["id"], unique=False)
    op.create_index(op.f("ix_ocpi_tariffs_tariff_id"), "ocpi_tariffs", ["tariff_id"], unique=True)


def downgrade() -> None:
    op.drop_table("ocpi_tariffs")
    op.drop_table("ocpi_command_results")
    op.drop_table("ocpi_cdrs")
    op.drop_table("ocpi_tokens")
    op.drop_table("ocpi_parties")
