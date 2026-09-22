"""add keycloak_sub to users (egyseges Energiafelho-fiok osszekotes)

Revision ID: e5c1a7b3d9f2
Revises: b7d4e2a91c38
Create Date: 2026-09-22 10:00:00.000000

Additív: egy nullable, egyedi oszlop. A meglévő (e-mail-kódos) fiókokat nem érinti.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e5c1a7b3d9f2"
down_revision: Union[str, Sequence[str], None] = "b7d4e2a91c38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("keycloak_sub", sa.String(64), nullable=True))
    op.create_index("ix_users_keycloak_sub", "users", ["keycloak_sub"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_keycloak_sub", table_name="users")
    op.drop_column("users", "keycloak_sub")
