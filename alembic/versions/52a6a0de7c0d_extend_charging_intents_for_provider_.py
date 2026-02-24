"""extend charging_intents for provider-agnostic payments

Revision ID: 52a6a0de7c0d
Revises: 42af0485197b
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "52a6a0de7c0d"
down_revision = "42af0485197b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) provider-agnostic mezők
    op.add_column("charging_intents", sa.Column("payment_provider", sa.String(length=32), nullable=True))
    op.add_column("charging_intents", sa.Column("payment_status", sa.String(length=64), nullable=True))
    op.add_column(
        "charging_intents",
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="huf"),
    )
    op.add_column("charging_intents", sa.Column("amount_huf", sa.Integer(), nullable=True))
    op.add_column("charging_intents", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("charging_intents", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("charging_intents", sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("charging_intents", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    # 2) stripe specifikus régi oszlop -> új név (csak ha a régi létezik és az új nem)
    # Postgres safe: DO blokkal lekérdezzük az oszlopokat.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='charging_intents' AND column_name='stripe_checkout_session_id'
            )
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='charging_intents' AND column_name='payment_session_id'
            )
            THEN
                ALTER TABLE charging_intents
                RENAME COLUMN stripe_checkout_session_id TO payment_session_id;
            END IF;
        END $$;
        """
    )

    # 3) indexek: csak ha a cél oszlop létezik
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='charging_intents' AND column_name='payment_session_id'
            )
            THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_charging_intents_payment_session_id ON charging_intents (payment_session_id)';
            END IF;

            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='charging_intents' AND column_name='payment_provider'
            )
            THEN
                EXECUTE 'CREATE INDEX IF NOT EXISTS ix_charging_intents_payment_provider ON charging_intents (payment_provider)';
            END IF;
        END $$;
        """
    )

    # 4) backfill: ha van payment_session_id, provider stripe
    op.execute(
        """
        UPDATE charging_intents
        SET payment_provider = COALESCE(payment_provider, 'stripe')
        WHERE
          (CASE
            WHEN EXISTS (
              SELECT 1 FROM information_schema.columns
              WHERE table_name='charging_intents' AND column_name='payment_session_id'
            )
            THEN payment_session_id IS NOT NULL
            ELSE FALSE
          END);
        """
    )

    # 5) updated_at kitöltés
    op.execute(
        "UPDATE charging_intents SET updated_at = COALESCE(updated_at, created_at) WHERE updated_at IS NULL"
    )

    # 6) server_default levétele (ne ragadjon ott)
    with op.batch_alter_table("charging_intents") as batch:
        batch.alter_column("currency", server_default=None)


def downgrade() -> None:
    # 1) indexek törlése (ha vannak)
    op.execute("DROP INDEX IF EXISTS ix_charging_intents_payment_provider")
    op.execute("DROP INDEX IF EXISTS ix_charging_intents_payment_session_id")

    # 2) új név vissza régire, csak ha payment_session_id létezik és stripe... nem
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='charging_intents' AND column_name='payment_session_id'
            )
            AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='charging_intents' AND column_name='stripe_checkout_session_id'
            )
            THEN
                ALTER TABLE charging_intents
                RENAME COLUMN payment_session_id TO stripe_checkout_session_id;
            END IF;
        END $$;
        """
    )

    # 3) mezők droppolása
    op.drop_column("charging_intents", "updated_at")
    op.drop_column("charging_intents", "expired_at")
    op.drop_column("charging_intents", "cancelled_at")
    op.drop_column("charging_intents", "paid_at")
    op.drop_column("charging_intents", "amount_huf")
    op.drop_column("charging_intents", "currency")
    op.drop_column("charging_intents", "payment_status")
    op.drop_column("charging_intents", "payment_provider")
