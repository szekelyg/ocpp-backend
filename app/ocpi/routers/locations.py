"""OCPI Locations module (CPO = Sender).

  GET /ocpi/2.2.1/locations                                  (paginated list)
  GET /ocpi/2.2.1/locations/{location_id}
  GET /ocpi/2.2.1/locations/{location_id}/{evse_uid}
  GET /ocpi/2.2.1/locations/{location_id}/{evse_uid}/{connector_id}
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.db.models import ChargePoint, Location as LocationORM, OcpiParty

from .. import OCPI_VERSION, ids, status_codes
from ..auth import require_party
from ..envelope import ok
from ..errors import OCPIException
from ..mappers.locations import connector_from_cp, evse_from_cp, find_evse, location_from_orm
from ..pagination import pagination_headers, parse_page

router = APIRouter(prefix=f"/{OCPI_VERSION}/locations", tags=["ocpi-locations"])


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise OCPIException(status_codes.INVALID_PARAMETERS, f"Invalid date: {value}")


def _updated_expr():
    return func.coalesce(LocationORM.ocpi_last_updated, LocationORM.updated_at)


def _has_published_evse():
    """Csak olyan Location megy ki, amin van legalább egy publikált töltő.

    Egy frissen felcsatlakozott, még konfigurálatlan töltő nem szivároghat ki a
    roaming partnerekhez, és üres EVSE-listás Location-t sem hirdetünk meg.
    """
    return (
        select(ChargePoint.id)
        .where(
            ChargePoint.location_id == LocationORM.id,
            ChargePoint.is_published.is_(True),
        )
        .exists()
    )


async def _load_location(db: AsyncSession, location_id: str) -> LocationORM:
    pk = ids.parse_location_id(location_id)
    if pk is None:
        raise OCPIException(status_codes.UNKNOWN_RESOURCE, "Unknown location", http_status=404)
    loc = (
        await db.execute(
            select(LocationORM)
            .options(selectinload(LocationORM.charge_points).selectinload(ChargePoint.location))
            .where(LocationORM.id == pk, _has_published_evse())
        )
    ).scalar_one_or_none()
    if loc is None:
        raise OCPIException(status_codes.UNKNOWN_RESOURCE, "Unknown location", http_status=404)
    return loc


@router.get("")
async def list_locations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _party: OcpiParty = Depends(require_party),
    offset: int = 0,
    limit: int = None,  # noqa: RUF013 (OCPI clamps via parse_page)
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    page = parse_page(offset, limit)
    df, dt = _parse_dt(date_from), _parse_dt(date_to)

    conds = [_has_published_evse()]
    if df is not None:
        conds.append(_updated_expr() >= df)
    if dt is not None:
        conds.append(_updated_expr() < dt)

    total = (await db.execute(select(func.count()).select_from(LocationORM).where(*conds))).scalar_one()

    rows = (
        await db.execute(
            select(LocationORM)
            .options(selectinload(LocationORM.charge_points).selectinload(ChargePoint.location))
            .where(*conds)
            .order_by(LocationORM.id)
            .offset(page.offset)
            .limit(page.limit)
        )
    ).scalars().all()

    data = [location_from_orm(loc) for loc in rows]
    return ok(data, headers=pagination_headers(request, page, total))


@router.get("/{location_id}")
async def get_location(location_id: str, db: AsyncSession = Depends(get_db), _party: OcpiParty = Depends(require_party)):
    loc = await _load_location(db, location_id)
    return ok(location_from_orm(loc))


@router.get("/{location_id}/{evse_uid}")
async def get_evse(location_id: str, evse_uid: str, db: AsyncSession = Depends(get_db), _party: OcpiParty = Depends(require_party)):
    loc = await _load_location(db, location_id)
    cp = find_evse(loc, evse_uid)
    if cp is None:
        raise OCPIException(status_codes.UNKNOWN_RESOURCE, "Unknown EVSE", http_status=404)
    return ok(evse_from_cp(cp))


@router.get("/{location_id}/{evse_uid}/{connector_id}")
async def get_connector(
    location_id: str,
    evse_uid: str,
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    _party: OcpiParty = Depends(require_party),
):
    loc = await _load_location(db, location_id)
    cp = find_evse(loc, evse_uid)
    if cp is None:
        raise OCPIException(status_codes.UNKNOWN_RESOURCE, "Unknown EVSE", http_status=404)
    if connector_id != ids.DEFAULT_CONNECTOR_ID:
        raise OCPIException(status_codes.UNKNOWN_RESOURCE, "Unknown connector", http_status=404)
    return ok(connector_from_cp(cp))
