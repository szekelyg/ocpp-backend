# app/api/routers/sessions.py

from __future__ import annotations

import hashlib
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

# ---------------------------------------------------------------------------
# Stop code rate limiting (in-memory, single-process MVP)
# ---------------------------------------------------------------------------
_STOP_ATTEMPTS: dict[int, list[datetime]] = {}
_MAX_STOP_ATTEMPTS = 5
_STOP_WINDOW_S = 600  # 10 perc


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _check_and_record_stop_attempt(session_id: int) -> None:
    now = _utcnow()
    history = [
        t for t in _STOP_ATTEMPTS.get(session_id, [])
        if (now - t).total_seconds() < _STOP_WINDOW_S
    ]
    if len(history) >= _MAX_STOP_ATTEMPTS:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "too_many_attempts",
                "hint": "Túl sok sikertelen kísérlet. Próbáld újra 10 perc múlva.",
            },
        )
    history.append(now)
    _STOP_ATTEMPTS[session_id] = history


def _verify_stop_code(session: ChargeSession, code: str) -> bool:
    if not session.stop_code_hash:
        return False
    h = hashlib.sha256(code.upper().strip().encode("utf-8")).hexdigest()
    return h == session.stop_code_hash


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _duration_s(s: ChargeSession) -> Optional[int]:
    if not s.started_at:
        return None
    start = s.started_at if s.started_at.tzinfo else s.started_at.replace(tzinfo=timezone.utc)
    end = s.finished_at if s.finished_at else _utcnow()
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - start).total_seconds()))


def _session_to_dict(s: ChargeSession, cp: Optional[ChargePoint] = None) -> dict:
    result: dict = {
        "id": s.id,
        "charge_point_id": s.charge_point_id,
        "connector_id": s.connector_id,
        "ocpp_transaction_id": s.ocpp_transaction_id,
        "user_tag": s.user_tag,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        "energy_kwh": s.energy_kwh,
        "cost_huf": s.cost_huf,
        "is_active": s.finished_at is None,
        "duration_s": _duration_s(s),
        "timed_out": s.finished_at is not None and s.ocpp_transaction_id is None,
    }
    if cp is not None:
        result["charge_point"] = {
            "ocpp_id": cp.ocpp_id,
            "status": cp.status,
            "model": cp.model,
            "vendor": cp.vendor,
        }
    return result


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


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class StartSessionIn(BaseModel):
    charge_point_id: int = Field(..., ge=1)
    connector_id: int = Field(1, ge=0)
    user_tag: str = Field("ANON", min_length=1, max_length=64)


class StopSessionIn(BaseModel):
    session_id: int = Field(..., ge=1)


class StopWithCodeIn(BaseModel):
    stop_code: str = Field(..., min_length=1, max_length=16)


# ---------------------------------------------------------------------------
# Routes – sorrendben: specifikusabb előbb, /{session_id} utoljára
# ---------------------------------------------------------------------------

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


@router.get("/active/by-charge-point/{cp_id}", response_model=dict)
async def get_active_session_for_cp(
    cp_id: int,
    connector_id: Optional[int] = Query(None, ge=0),
    db: AsyncSession = Depends(get_db),
):
    s = await _get_active_session(db, charge_point_id=cp_id, connector_id=connector_id)
    if not s:
        raise HTTPException(status_code=404, detail="No active session")
    return _session_to_dict(s)


@router.get("/by-intent/{intent_id}", response_model=dict)
async def get_session_by_intent(
    intent_id: int,
    db: AsyncSession = Depends(get_db),
):
    """PaySuccess polling: session keresése intent_id alapján."""
    res = await db.execute(
        select(ChargeSession)
        .options(selectinload(ChargeSession.charge_point))
        .where(ChargeSession.intent_id == intent_id)
        .limit(1)
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found for this intent")
    return _session_to_dict(s, s.charge_point)


@router.post("/start", response_model=dict)
async def start_session(
    body: StartSessionIn,
    db: AsyncSession = Depends(get_db),
):
    cp = await _get_cp_by_id(db, body.charge_point_id)

    existing = await _get_active_session(db, charge_point_id=cp.id, connector_id=body.connector_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "active_session_exists",
                "session": _session_to_dict(existing),
            },
        )

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
            detail={"error": "remote_start_rejected", "ocpp": ocpp_res},
        )

    return {
        "ok": True,
        "ocpp": ocpp_res,
        "hint": "Wait for StartTransaction; session will be created by OCPP handler.",
    }


@router.post("/stop", response_model=dict)
async def stop_session(
    body: StopSessionIn,
    db: AsyncSession = Depends(get_db),
):
    """Belső / admin stop – stop_code nélkül."""
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

    if not s.ocpp_transaction_id:
        raise HTTPException(
            status_code=409,
            detail={"error": "missing_ocpp_transaction_id"},
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

    return {"ok": True, "ocpp": ocpp_res, "session": _session_to_dict(s)}


@router.get("/{session_id}", response_model=dict)
async def get_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(ChargeSession)
        .options(selectinload(ChargeSession.charge_point))
        .where(ChargeSession.id == session_id)
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_to_dict(s, s.charge_point)


@router.post("/{session_id}/stop", response_model=dict)
async def stop_session_with_code(
    session_id: int,
    body: StopWithCodeIn,
    db: AsyncSession = Depends(get_db),
):
    """Publikus stop – stop_code ellenőrzéssel + rate limittel."""
    # Rate limit ellenőrzés (minden próbálkozásnál, sikeres előtt)
    _check_and_record_stop_attempt(session_id)

    res = await db.execute(
        select(ChargeSession)
        .options(selectinload(ChargeSession.charge_point))
        .where(ChargeSession.id == session_id)
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")

    if s.finished_at is not None:
        return {"ok": True, "already_finished": True, "session": _session_to_dict(s, s.charge_point)}

    # Stop code ellenőrzés
    if not _verify_stop_code(s, body.stop_code):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "invalid_stop_code",
                "hint": "Helytelen stop kód. Ellenőrizd az emailben kapott kódot.",
            },
        )

    # Sikeres auth → töröljük a rate limit előzményt
    _STOP_ATTEMPTS.pop(session_id, None)

    if not s.charge_point:
        raise HTTPException(status_code=500, detail="Session has no charge_point")

    if not s.ocpp_transaction_id:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "missing_ocpp_transaction_id",
                "hint": "A töltés még nem indult el teljesen, kérjük várj pár másodpercet.",
            },
        )

    try:
        ocpp_res = await remote_stop_transaction(
            cp_id=str(s.charge_point.ocpp_id),
            transaction_id=s.ocpp_transaction_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "ocpp_remote_stop_failed", "reason": str(e)})

    ocpp_status = (ocpp_res or {}).get("status")
    if ocpp_status not in ("Accepted", "accepted"):
        raise HTTPException(status_code=409, detail={"error": "remote_stop_rejected", "ocpp": ocpp_res})

    return {"ok": True, "ocpp": ocpp_res, "session": _session_to_dict(s, s.charge_point)}
