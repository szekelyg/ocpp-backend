from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.deps import get_db
from app.db.models import ChargePoint

router = APIRouter(prefix="/charge-points", tags=["charge-points"])


@router.get("/", response_model=list[dict])
async def list_charge_points(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ChargePoint))
    items = result.scalars().all()

    # most egyszerűen dict-et adunk vissza, később csinálhatunk Pydantic sémát
    return [
        {
            "id": cp.id,
            "ocpp_id": cp.ocpp_id,
            "model": cp.model,
            "vendor": cp.vendor,
            "status": cp.status,
            "last_seen_at": cp.last_seen_at.isoformat() if cp.last_seen_at else None,
        }
        for cp in items
    ]


@router.get("/{cp_id}", response_model=dict)
async def get_charge_point(
    cp_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ChargePoint).where(ChargePoint.id == cp_id)
    )
    cp = result.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint not found")

    return {
        "id": cp.id,
        "ocpp_id": cp.ocpp_id,
        "model": cp.model,
        "vendor": cp.vendor,
        "status": cp.status,
        "last_seen_at": cp.last_seen_at.isoformat() if cp.last_seen_at else None,
    }