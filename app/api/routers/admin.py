# app/api/routers/admin.py
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Header
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.db.models import ChargePoint, ChargeSession, ChargingIntent, Location, MeterSample
from app.ocpp.ocpp_ws import remote_start_transaction, remote_stop_transaction

logger = logging.getLogger("admin")

router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Auth config – env vars, fallback defaults
# ---------------------------------------------------------------------------

_ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
_ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "sevenof9")
_ADMIN_SECRET = os.environ.get("ADMIN_SECRET_KEY", "ocpp-admin-secret-change-me-in-prod")
_TOKEN_TTL = 86400 * 7  # 7 nap


def _make_token(username: str) -> str:
    payload = json.dumps({"sub": username, "exp": int(time.time()) + _TOKEN_TTL})
    b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_ADMIN_SECRET.encode(), b64.encode(), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"


def _verify_token(token: str) -> Optional[str]:
    try:
        b64, sig = token.rsplit(".", 1)
        expected = hmac.new(_ADMIN_SECRET.encode(), b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(b64 + "==").decode())
        if payload.get("exp", 0) < time.time():
            return None
        return payload.get("sub")
    except Exception:
        return None


async def get_admin_user(authorization: str = Header(default="")):
    """Dependency: Bearer token ellenőrzés."""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Hiányzó vagy érvénytelen token")
    sub = _verify_token(token)
    if not sub:
        raise HTTPException(status_code=401, detail="Érvénytelen vagy lejárt token")
    return sub


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class LoginIn(BaseModel):
    username: str
    password: str


class CreateChargePointIn(BaseModel):
    ocpp_id: str = Field(..., min_length=1, max_length=64)
    model: Optional[str] = None
    vendor: Optional[str] = None
    serial_number: Optional[str] = None
    location_id: Optional[int] = None


class UpdateChargePointIn(BaseModel):
    model: Optional[str] = None
    vendor: Optional[str] = None
    serial_number: Optional[str] = None
    firmware_version: Optional[str] = None
    status: Optional[str] = None
    location_id: Optional[int] = None


class AdminStartIn(BaseModel):
    charge_point_id: int = Field(..., ge=1)
    connector_id: int = Field(1, ge=0)
    user_tag: str = Field("ADMIN", min_length=1, max_length=64)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow():
    return datetime.now(timezone.utc)


def _duration_s(s: ChargeSession) -> Optional[int]:
    if not s.started_at:
        return None
    start = s.started_at if s.started_at.tzinfo else s.started_at.replace(tzinfo=timezone.utc)
    end = s.finished_at if s.finished_at else _utcnow()
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - start).total_seconds()))


def _session_dict(s: ChargeSession) -> dict:
    cp = s.charge_point
    return {
        "id": s.id,
        "charge_point_id": s.charge_point_id,
        "charge_point_ocpp_id": cp.ocpp_id if cp else None,
        "connector_id": s.connector_id,
        "ocpp_transaction_id": s.ocpp_transaction_id,
        "user_tag": s.user_tag,
        "anonymous_email": s.anonymous_email,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        "energy_kwh": s.energy_kwh,
        "cost_huf": s.cost_huf,
        "meter_start_wh": s.meter_start_wh,
        "meter_stop_wh": s.meter_stop_wh,
        "is_active": s.finished_at is None,
        "duration_s": _duration_s(s),
        "timed_out": s.finished_at is not None and s.ocpp_transaction_id is None,
        "intent_id": s.intent_id,
    }


def _cp_dict(cp: ChargePoint) -> dict:
    loc = cp.location
    return {
        "id": cp.id,
        "ocpp_id": cp.ocpp_id,
        "model": cp.model,
        "vendor": cp.vendor,
        "serial_number": cp.serial_number,
        "firmware_version": cp.firmware_version,
        "status": cp.status,
        "last_seen_at": cp.last_seen_at.isoformat() if cp.last_seen_at else None,
        "location_id": cp.location_id,
        "location_name": loc.name if loc else None,
        "location_address": loc.address_text if loc else None,
        "created_at": cp.created_at.isoformat() if cp.created_at else None,
    }


def _intent_dict(i: ChargingIntent) -> dict:
    cp = i.charge_point
    return {
        "id": i.id,
        "charge_point_id": i.charge_point_id,
        "charge_point_ocpp_id": cp.ocpp_id if cp else None,
        "connector_id": i.connector_id,
        "anonymous_email": i.anonymous_email,
        "status": i.status,
        "hold_amount_huf": i.hold_amount_huf,
        "payment_provider": i.payment_provider,
        "payment_provider_ref": i.payment_provider_ref,
        "cancel_reason": i.cancel_reason,
        "expires_at": i.expires_at.isoformat() if i.expires_at else None,
        "created_at": i.created_at.isoformat() if i.created_at else None,
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@router.post("/login")
async def admin_login(body: LoginIn):
    if body.username != _ADMIN_USERNAME or body.password != _ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Hibás felhasználónév vagy jelszó")
    token = _make_token(body.username)
    return {
        "token": token,
        "expires_at": int(time.time()) + _TOKEN_TTL,
        "username": body.username,
    }


# ---------------------------------------------------------------------------
# Stats / Dashboard
# ---------------------------------------------------------------------------

@router.get("/stats")
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    # Total sessions
    total_sessions = (await db.execute(select(func.count(ChargeSession.id)))).scalar_one()

    # Active sessions
    active_sessions = (await db.execute(
        select(func.count(ChargeSession.id)).where(ChargeSession.finished_at.is_(None))
    )).scalar_one()

    # Total energy
    total_energy = (await db.execute(
        select(func.sum(ChargeSession.energy_kwh)).where(ChargeSession.energy_kwh.isnot(None))
    )).scalar_one() or 0.0

    # Total revenue
    total_revenue = (await db.execute(
        select(func.sum(ChargeSession.cost_huf)).where(ChargeSession.cost_huf.isnot(None))
    )).scalar_one() or 0.0

    # Charge points
    total_cps = (await db.execute(select(func.count(ChargePoint.id)))).scalar_one()

    # Online CPs (last heartbeat < 5 min)
    cutoff = _utcnow()
    from datetime import timedelta
    online_cutoff = cutoff - timedelta(minutes=5)
    online_cps = (await db.execute(
        select(func.count(ChargePoint.id)).where(ChargePoint.last_seen_at >= online_cutoff)
    )).scalar_one()

    # Intents today
    today_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sessions_today = (await db.execute(
        select(func.count(ChargeSession.id)).where(ChargeSession.started_at >= today_start)
    )).scalar_one()

    revenue_today = (await db.execute(
        select(func.sum(ChargeSession.cost_huf)).where(
            and_(ChargeSession.started_at >= today_start, ChargeSession.cost_huf.isnot(None))
        )
    )).scalar_one() or 0.0

    return {
        "total_sessions": total_sessions,
        "active_sessions": active_sessions,
        "sessions_today": sessions_today,
        "total_energy_kwh": round(total_energy, 2),
        "total_revenue_huf": round(total_revenue, 0),
        "revenue_today_huf": round(revenue_today, 0),
        "total_charge_points": total_cps,
        "online_charge_points": online_cps,
    }


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@router.get("/sessions")
async def admin_list_sessions(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_admin_user),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active_only: bool = Query(False),
    cp_id: Optional[int] = Query(None),
    email: Optional[str] = Query(None),
):
    conds = []
    if active_only:
        conds.append(ChargeSession.finished_at.is_(None))
    if cp_id is not None:
        conds.append(ChargeSession.charge_point_id == cp_id)
    if email:
        conds.append(ChargeSession.anonymous_email.ilike(f"%{email}%"))

    stmt = select(ChargeSession).options(selectinload(ChargeSession.charge_point))
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(desc(ChargeSession.started_at)).offset(offset).limit(limit)

    result = await db.execute(stmt)
    sessions = result.scalars().all()

    # Total count
    count_stmt = select(func.count(ChargeSession.id))
    if conds:
        count_stmt = count_stmt.where(and_(*conds))
    total = (await db.execute(count_stmt)).scalar_one()

    return {"total": total, "sessions": [_session_dict(s) for s in sessions]}


@router.post("/sessions/remote-start")
async def admin_remote_start(
    body: AdminStartIn,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    res = await db.execute(select(ChargePoint).where(ChargePoint.id == body.charge_point_id))
    cp = res.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint nem található")

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
        raise HTTPException(status_code=409, detail={"error": "remote_start_rejected", "ocpp": ocpp_res})

    return {"ok": True, "ocpp": ocpp_res}


@router.post("/sessions/{session_id}/stop")
async def admin_stop_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    res = await db.execute(
        select(ChargeSession)
        .options(selectinload(ChargeSession.charge_point))
        .where(ChargeSession.id == session_id)
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session nem található")

    if s.finished_at is not None:
        return {"ok": True, "already_finished": True}

    if not s.ocpp_transaction_id:
        raise HTTPException(status_code=409, detail={"error": "missing_ocpp_transaction_id"})

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

    return {"ok": True, "ocpp": ocpp_res}


# ---------------------------------------------------------------------------
# Charge Points
# ---------------------------------------------------------------------------

@router.get("/charge-points")
async def admin_list_cps(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    result = await db.execute(
        select(ChargePoint)
        .options(selectinload(ChargePoint.location))
        .order_by(ChargePoint.id)
    )
    cps = result.scalars().all()
    return [_cp_dict(cp) for cp in cps]


@router.post("/charge-points")
async def admin_create_cp(
    body: CreateChargePointIn,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    # Duplikáció ellenőrzés
    existing = (await db.execute(
        select(ChargePoint).where(ChargePoint.ocpp_id == body.ocpp_id)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"ocpp_id '{body.ocpp_id}' már létezik")

    cp = ChargePoint(
        ocpp_id=body.ocpp_id,
        model=body.model,
        vendor=body.vendor,
        serial_number=body.serial_number,
        location_id=body.location_id,
        status="available",
    )
    db.add(cp)
    await db.commit()
    await db.refresh(cp)
    return _cp_dict(cp)


@router.put("/charge-points/{cp_id}")
async def admin_update_cp(
    cp_id: int,
    body: UpdateChargePointIn,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    res = await db.execute(
        select(ChargePoint).options(selectinload(ChargePoint.location)).where(ChargePoint.id == cp_id)
    )
    cp = res.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint nem található")

    if body.model is not None:
        cp.model = body.model
    if body.vendor is not None:
        cp.vendor = body.vendor
    if body.serial_number is not None:
        cp.serial_number = body.serial_number
    if body.firmware_version is not None:
        cp.firmware_version = body.firmware_version
    if body.status is not None:
        cp.status = body.status
    if body.location_id is not None:
        cp.location_id = body.location_id

    await db.commit()
    await db.refresh(cp)
    return _cp_dict(cp)


@router.delete("/charge-points/{cp_id}")
async def admin_delete_cp(
    cp_id: int,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_admin_user),
):
    res = await db.execute(select(ChargePoint).where(ChargePoint.id == cp_id))
    cp = res.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint nem található")

    await db.delete(cp)
    await db.commit()
    return {"ok": True, "deleted_id": cp_id}


# ---------------------------------------------------------------------------
# Intents (fizetési szándékok)
# ---------------------------------------------------------------------------

@router.get("/intents")
async def admin_list_intents(
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_admin_user),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
):
    conds = []
    if status:
        conds.append(ChargingIntent.status == status)

    stmt = select(ChargingIntent).options(selectinload(ChargingIntent.charge_point))
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(desc(ChargingIntent.created_at)).offset(offset).limit(limit)

    result = await db.execute(stmt)
    intents = result.scalars().all()

    count_stmt = select(func.count(ChargingIntent.id))
    if conds:
        count_stmt = count_stmt.where(and_(*conds))
    total = (await db.execute(count_stmt)).scalar_one()

    return {"total": total, "intents": [_intent_dict(i) for i in intents]}
