from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.db.models import ChargePoint

router = APIRouter(prefix="/charge-points", tags=["charge-points"])

OFFLINE_TTL = timedelta(seconds=120)


def compute_status(cp: ChargePoint) -> str:
    if not cp.last_seen_at:
        return "offline"

    now = datetime.now(timezone.utc)

    if now - cp.last_seen_at > OFFLINE_TTL:
        return "offline"

    return cp.status or "unknown"


@router.get("/", response_model=list[dict])
async def list_charge_points(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChargePoint).options(selectinload(ChargePoint.location))
    )
    items = result.scalars().all()

    response = []

    for cp in items:
        response.append({
            "id": cp.id,
            "ocpp_id": cp.ocpp_id,
            "model": cp.model,
            "vendor": cp.vendor,
            "status": compute_status(cp),
            "last_seen_at": cp.last_seen_at.isoformat() if cp.last_seen_at else None,
            "location_name": cp.location.name if cp.location else None,
            "address_text": cp.location.address_text if cp.location else None,
            "latitude": float(cp.location.latitude) if cp.location and cp.location.latitude else None,
            "longitude": float(cp.location.longitude) if cp.location and cp.location.longitude else None,
        })

    return response


@router.get("/{cp_id}", response_model=dict)
async def get_charge_point(cp_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ChargePoint)
        .options(selectinload(ChargePoint.location))
        .where(ChargePoint.id == cp_id)
    )
    cp = result.scalar_one_or_none()

    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint not found")

    return {
        "id": cp.id,
        "ocpp_id": cp.ocpp_id,
        "model": cp.model,
        "vendor": cp.vendor,
        "status": compute_status(cp),
        "last_seen_at": cp.last_seen_at.isoformat() if cp.last_seen_at else None,
        "location_name": cp.location.name if cp.location else None,
        "address_text": cp.location.address_text if cp.location else None,
        "latitude": float(cp.location.latitude) if cp.location and cp.location.latitude else None,
        "longitude": float(cp.location.longitude) if cp.location and cp.location.longitude else None,
    }