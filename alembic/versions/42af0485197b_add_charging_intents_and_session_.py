"""add charging_intents and session ownership fields

Revision ID: 42af0485197b
Revises: 50dda8dce6d6>
"""

from alembic import op
import sqlalchemy as sa


revision = "42af0485197b"
down_revision = "50dda8dce6d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "charging_intents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("charge_point_id", sa.Integer(), sa.ForeignKey("charge_points.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connector_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("anonymous_email", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_payment"),
        sa.Column("hold_amount_huf", sa.Integer(), nullable=False, server_default="5000"),
        sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_charging_intents_stripe_checkout_session_id", "charging_intents", ["stripe_checkout_session_id"])

    op.add_column("charge_sessions", sa.Column("anonymous_email", sa.String(length=255), nullable=True))
    op.add_column("charge_sessions", sa.Column("intent_id", sa.Integer(), sa.ForeignKey("charging_intents.id", ondelete="SET NULL"), nullable=True))
    op.add_column("charge_sessions", sa.Column("stop_code_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("charge_sessions", "stop_code_hash")
    op.drop_column("charge_sessions", "intent_id")
    op.drop_column("charge_sessions", "anonymous_email")

    op.drop_index("ix_charging_intents_stripe_checkout_session_id", table_name="charging_intents")
    op.drop_table("charging_intents")
