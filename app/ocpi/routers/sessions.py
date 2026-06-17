"""OCPI Sessions module (CPO = Sender).

  GET /ocpi/2.2.1/sessions               (paginated list)
  GET /ocpi/2.2.1/sessions/{session_id}
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.db.models import ChargeSession, OcpiParty

from .. import OCPI_VERSION, status_codes
from ..auth import require_party
from ..envelope import ok, parse_ocpi_datetime
from ..errors import OCPIException
from ..mappers.sessions import session_from_orm
from ..pagination import pagination_headers, parse_page

router = APIRouter(prefix=f"/{OCPI_VERSION}/sessions", tags=["ocpi-sessions"])


def _qdate(value: Optional[str]) -> Optional[datetime]:
    try:
        return parse_ocpi_datetime(value)
    except ValueError:
        raise OCPIException(status_codes.INVALID_PARAMETERS, f"Invalid date: {value}")


def _updated_expr():
    return func.coalesce(ChargeSession.ocpi_last_updated, ChargeSession.updated_at)


@router.get("")
async def list_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _party: OcpiParty = Depends(require_party),
    offset: int = 0,
    limit: int = None,  # noqa: RUF013
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    page = parse_page(offset, limit)
    df, dt = _qdate(date_from), _qdate(date_to)

    conds = []
    if df is not None:
        conds.append(_updated_expr() >= df)
    if dt is not None:
        conds.append(_updated_expr() < dt)

    total = (await db.execute(select(func.count()).select_from(ChargeSession).where(*conds))).scalar_one()
    rows = (
        await db.execute(
            select(ChargeSession)
            .options(selectinload(ChargeSession.charge_point))
            .where(*conds)
            .order_by(ChargeSession.id)
            .offset(page.offset)
            .limit(page.limit)
        )
    ).scalars().all()

    data = [session_from_orm(cs) for cs in rows]
    return ok(data, headers=pagination_headers(request, page, total))


@router.get("/{session_id}")
async def get_session(session_id: str, db: AsyncSession = Depends(get_db), _party: OcpiParty = Depends(require_party)):
    conds = [ChargeSession.ocpi_session_id == session_id]
    if session_id.isdigit():
        conds.append(ChargeSession.id == int(session_id))
    cs = (
        await db.execute(
            select(ChargeSession)
            .options(selectinload(ChargeSession.charge_point))
            .where(or_(*conds))
        )
    ).scalar_one_or_none()
    if cs is None:
        raise OCPIException(status_codes.UNKNOWN_RESOURCE, "Unknown session", http_status=404)
    return ok(session_from_orm(cs))
