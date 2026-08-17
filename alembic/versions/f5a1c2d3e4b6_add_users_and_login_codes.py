"""add users and login_codes (passwordless accounts + saved billing profile)

Revision ID: f5a1c2d3e4b6
Revises: c1b2c3d4e5f6
Create Date: 2026-07-01 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f5a1c2d3e4b6"
down_revision: Union[str, Sequence[str], None] = "c1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("billing_type", sa.String(16), nullable=True),
        sa.Column("billing_name", sa.String(255), nullable=True),
        sa.Column("billing_street", sa.String(255), nullable=True),
        sa.Column("billing_zip", sa.String(16), nullable=True),
        sa.Column("billing_city", sa.String(128), nullable=True),
        sa.Column("billing_country", sa.String(4), nullable=True),
        sa.Column("billing_company", sa.String(255), nullable=True),
        sa.Column("billing_tax_number", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_unique_constraint("uq_users_email", "users", ["email"])
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "login_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_login_codes_id", "login_codes", ["id"])
    op.create_index("ix_login_codes_email", "login_codes", ["email"])
    op.create_index("ix_login_codes_expires_at", "login_codes", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_login_codes_expires_at", table_name="login_codes")
    op.drop_index("ix_login_codes_email", table_name="login_codes")
    op.drop_index("ix_login_codes_id", table_name="login_codes")
    op.drop_table("login_codes")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
