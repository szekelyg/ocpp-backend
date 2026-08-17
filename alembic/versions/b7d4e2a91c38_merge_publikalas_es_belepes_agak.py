"""merge: publikalasi ag (f1a2b3c4d5e6) + belepes/fazis ag (a7c3e1f9d2b4)

A projekt junius 17-en kettevalt: a GitHubon a toltő-publikalasi ag (is_published)
epult tovabb, helyben pedig a jelszo nelkuli belepes (users + login_codes) es a
fazisonkenti meres. Mindketto a c1b2c3d4e5f6-rol agazik le, ezert az osszefesules
utan ket head lett volna – amitol az `alembic upgrade head` elszall, es mivel a
migracio a kontener indulasakor fut, a backend fel sem jonne.

Ez a revizio csak osszekoti a ket agat, semat nem valtoztat.

Revision ID: b7d4e2a91c38
Revises: a7c3e1f9d2b4, f1a2b3c4d5e6
Create Date: 2026-08-17
"""
from typing import Sequence, Union

revision: str = "b7d4e2a91c38"
down_revision: Union[str, Sequence[str], None] = ("a7c3e1f9d2b4", "f1a2b3c4d5e6")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
