# app/api/routers/sessions.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.db.models import ChargePoint, ChargeSession
from app.ocpp.ocpp_ws import remote_start_transaction, remote_stop_transaction

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _session_to_dict(s: ChargeSession) -> dict:
    return {
        "id": s.id,
        "charge_point_id": s.charge_point_id,
        "connector_id": s.connector_id,
        "ocpp_transaction_id": s.ocpp_transaction_id,
        "user_tag": s.user_tag,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        "energy_kwh": s.energy_kwh,
        "cost_huf": s.cost_huf,
    }


async def _get_cp_by_id(db: AsyncSession, cp_id: int) -> ChargePoint:
    res = await db.execute(select(ChargePoint).where(ChargePoint.id == cp_id))
    cp = res.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint not found")
    return cp


async def _get_active_session(
    db: AsyncSession,
    charge_point_id: int,
    connector_id: Optional[int] = None,
) -> Optional[ChargeSession]:
    conds = [ChargeSession.charge_point_id == charge_point_id, ChargeSession.finished_at.is_(None)]
    if connector_id is not None:
        conds.append(ChargeSession.connector_id == int(connector_id))

    res = await db.execute(
        select(ChargeSession)
        .where(and_(*conds))
        .order_by(desc(ChargeSession.started_at), desc(ChargeSession.id))
        .limit(1)
    )
    return res.scalar_one_or_none()


class StartSessionIn(BaseModel):
    charge_point_id: int = Field(..., ge=1)
    connector_id: int = Field(1, ge=0)  # 0 = "any" is valid in some CP impls, keep flexible
    user_tag: str = Field("ANON", min_length=1, max_length=64)


class StopSessionIn(BaseModel):
    session_id: int = Field(..., ge=1)


@router.get("/", response_model=list[dict])
async def list_sessions(
    db: AsyncSession = Depends(get_db),
    charge_point_id: Optional[int] = Query(None, ge=1),
    connector_id: Optional[int] = Query(None, ge=0),
    active_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    conds = []
    if charge_point_id is not None:
        conds.append(ChargeSession.charge_point_id == charge_point_id)
    if connector_id is not None:
        conds.append(ChargeSession.connector_id == connector_id)
    if active_only:
        conds.append(ChargeSession.finished_at.is_(None))

    stmt = (
        select(ChargeSession)
        .where(and_(*conds)) if conds else select(ChargeSession)
    )
    stmt = stmt.order_by(desc(ChargeSession.started_at), desc(ChargeSession.id)).offset(offset).limit(limit)

    result = await db.execute(stmt)
    sessions = result.scalars().all()
    return [_session_to_dict(s) for s in sessions]


@router.get("/{session_id}", response_model=dict)
async def get_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(select(ChargeSession).where(ChargeSession.id == session_id))
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_dict(s)


@router.get("/active/by-charge-point/{cp_id}", response_model=dict)
async def get_active_session_for_cp(
    cp_id: int,
    connector_id: Optional[int] = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
):
    # 404, ha nincs aktív (UI-nak egyszerűbb)
    s = await _get_active_session(db, charge_point_id=cp_id, connector_id=connector_id)
    if not s:
        raise HTTPException(status_code=404, detail="No active session")
    return _session_to_dict(s)


@router.post("/start", response_model=dict)
async def start_session(
    body: StartSessionIn,
    db: AsyncSession = Depends(get_db),
):
    cp = await _get_cp_by_id(db, body.charge_point_id)

    # 1 töltőn / 1 csatlakozón egyszerre csak 1 aktív session
    existing = await _get_active_session(db, charge_point_id=cp.id, connector_id=body.connector_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "active_session_exists",
                "session": _session_to_dict(existing),
            },
        )

    # OCPP RemoteStartTransaction -> CP (ocpp_id a WS registry kulcs)
    try:
        ocpp_res = await remote_start_transaction(
            cp_id=str(cp.ocpp_id),
            connector_id=int(body.connector_id),
            id_tag=str(body.user_tag),
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "ocpp_remote_start_failed", "reason": str(e)})

    status = (ocpp_res or {}).get("status")
    if status not in ("Accepted", "accepted"):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "remote_start_rejected",
                "ocpp": ocpp_res,
            },
        )

    # DB: létrehozunk egy "pending/active" sessiont.
    # Az ocpp_transaction_id tipikusan StartTransaction-ből jön később.
    s = ChargeSession(
        charge_point_id=cp.id,
        connector_id=int(body.connector_id),
        user_tag=str(body.user_tag),
        started_at=_utcnow(),
        finished_at=None,
        energy_kwh=None,
        cost_huf=None,
        ocpp_transaction_id=None,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)

    return {
        "ok": True,
        "ocpp": ocpp_res,
        "session": _session_to_dict(s),
    }


@router.post("/stop", response_model=dict)
async def stop_session(
    body: StopSessionIn,
    db: AsyncSession = Depends(get_db),
):
    # session betöltés + CP betöltés
    res = await db.execute(
        select(ChargeSession)
        .options(selectinload(ChargeSession.charge_point))
        .where(ChargeSession.id == body.session_id)
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    if s.finished_at is not None:
        return {"ok": True, "already_finished": True, "session": _session_to_dict(s)}

    if not s.charge_point:
        raise HTTPException(status_code=500, detail="Session has no charge_point relationship loaded")

    # OCPP RemoteStopTransaction kötelezően transactionId-t kér
    if not s.ocpp_transaction_id:
        raise HTTPException(
            status_code=409,
            detail={"error": "missing_ocpp_transaction_id", "hint": "Wait for StartTransaction or implement mapping."},
        )

    try:
        ocpp_res = await remote_stop_transaction(
            cp_id=str(s.charge_point.ocpp_id),
            transaction_id=s.ocpp_transaction_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "ocpp_remote_stop_failed", "reason": str(e)})

    status = (ocpp_res or {}).get("status")
    if status not in ("Accepted", "accepted"):
        raise HTTPException(status_code=409, detail={"error": "remote_stop_rejected", "ocpp": ocpp_res})

    # DB-ben itt nem zárjuk le erőből, mert a korrekt zárás tipikusan StopTransaction-ből jön.
    # Viszont adunk egy "soft" jelzést UI-nak.
    return {
        "ok": True,
        "ocpp": ocpp_res,
        "session": _session_to_dict(s),
    }