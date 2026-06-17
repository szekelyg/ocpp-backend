"""OCPI CDRs module (CPO = Sender). Reads immutable snapshots from ocpi_cdrs.

  GET /ocpi/2.2.1/cdrs            (paginated list)
  GET /ocpi/2.2.1/cdrs/{cdr_id}
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import OcpiCdr, OcpiParty

from .. import OCPI_VERSION, status_codes
from ..auth import require_party
from ..envelope import ok, parse_ocpi_datetime
from ..errors import OCPIException
from ..mappers.cdrs import cdr_orm_to_schema
from ..pagination import pagination_headers, parse_page

router = APIRouter(prefix=f"/{OCPI_VERSION}/cdrs", tags=["ocpi-cdrs"])


def _qdate(value: Optional[str]) -> Optional[datetime]:
    try:
        return parse_ocpi_datetime(value)
    except ValueError:
        raise OCPIException(status_codes.INVALID_PARAMETERS, f"Invalid date: {value}")


@router.get("")
async def list_cdrs(
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
        conds.append(OcpiCdr.last_updated >= df)
    if dt is not None:
        conds.append(OcpiCdr.last_updated < dt)

    total = (await db.execute(select(func.count()).select_from(OcpiCdr).where(*conds))).scalar_one()
    rows = (
        await db.execute(
            select(OcpiCdr).where(*conds).order_by(OcpiCdr.id).offset(page.offset).limit(page.limit)
        )
    ).scalars().all()

    data = [cdr_orm_to_schema(row) for row in rows]
    return ok(data, headers=pagination_headers(request, page, total))


@router.get("/{cdr_id}")
async def get_cdr(cdr_id: str, db: AsyncSession = Depends(get_db), _party: OcpiParty = Depends(require_party)):
    row = (await db.execute(select(OcpiCdr).where(OcpiCdr.cdr_id == cdr_id))).scalar_one_or_none()
    if row is None:
        raise OCPIException(status_codes.UNKNOWN_RESOURCE, "Unknown CDR", http_status=404)
    return ok(cdr_orm_to_schema(row))
