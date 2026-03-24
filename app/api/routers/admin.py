# app/api/routers/admin.py
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from app.api.routers.charge_points import compute_status

router = APIRouter(prefix="/admin", tags=["admin"])
_security = HTTPBasic()


def _admin_creds():
    return (
        os.environ.get("ADMIN_USERNAME", "admin"),
        os.environ.get("ADMIN_PASSWORD", "Sevenof9"),
    )


def verify_admin(credentials: HTTPBasicCredentials = Depends(_security)):
    exp_user, exp_pass = _admin_creds()
    ok = secrets.compare_digest(credentials.username.encode(), exp_user.encode()) and \
         secrets.compare_digest(credentials.password.encode(), exp_pass.encode())
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials


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
    intent = s.intent
    return {
        "id": s.id,
        "charge_point_id": s.charge_point_id,
        "charge_point_ocpp_id": cp.ocpp_id if cp else None,
        "charge_point_location": (cp.location.name if cp and cp.location else None),
        "connector_id": s.connector_id,
        "ocpp_transaction_id": s.ocpp_transaction_id,
        "user_tag": s.user_tag,
        "anonymous_email": s.anonymous_email,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        "is_active": s.finished_at is None,
        "timed_out": s.finished_at is not None and s.ocpp_transaction_id is None,
        "duration_s": _duration_s(s),
        "energy_kwh": s.energy_kwh,
        "cost_huf": s.cost_huf,
        "invoice_number": s.invoice_number,
        "intent": {
            "id": intent.id,
            "status": intent.status,
            "hold_amount_huf": intent.hold_amount_huf,
            "billing_type": intent.billing_type,
            "billing_name": intent.billing_name,
            "billing_company": intent.billing_company,
            "billing_city": intent.billing_city,
            "billing_country": intent.billing_country,
            "payment_provider": intent.payment_provider,
            "stripe_payment_intent_id": intent.stripe_payment_intent_id,
            "cancel_reason": intent.cancel_reason,
            "last_error": intent.last_error,
        } if intent else None,
    }


def _intent_dict(i: ChargingIntent) -> dict:
    return {
        "id": i.id,
        "charge_point_id": i.charge_point_id,
        "charge_point_ocpp_id": i.charge_point.ocpp_id if i.charge_point else None,
        "anonymous_email": i.anonymous_email,
        "status": i.status,
        "hold_amount_huf": i.hold_amount_huf,
        "payment_provider": i.payment_provider,
        "payment_provider_ref": i.payment_provider_ref,
        "stripe_payment_intent_id": i.stripe_payment_intent_id,
        "billing_type": i.billing_type,
        "billing_name": i.billing_name,
        "billing_company": i.billing_company,
        "billing_tax_number": i.billing_tax_number,
        "billing_street": i.billing_street,
        "billing_zip": i.billing_zip,
        "billing_city": i.billing_city,
        "billing_country": i.billing_country,
        "cancel_reason": i.cancel_reason,
        "last_error": i.last_error,
        "expires_at": i.expires_at.isoformat() if i.expires_at else None,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "updated_at": i.updated_at.isoformat() if i.updated_at else None,
    }


def _cp_dict_admin(cp: ChargePoint) -> dict:
    return {
        "id": cp.id,
        "ocpp_id": cp.ocpp_id,
        "model": cp.model,
        "vendor": cp.vendor,
        "firmware_version": cp.firmware_version,
        "serial_number": cp.serial_number,
        "connector_type": cp.connector_type,
        "max_power_kw": cp.max_power_kw,
        "status": compute_status(cp),
        "raw_status": cp.status,
        "last_seen_at": cp.last_seen_at.isoformat() if cp.last_seen_at else None,
        "location_name": cp.location.name if cp.location else None,
        "address_text": cp.location.address_text if cp.location else None,
        "latitude": float(cp.location.latitude) if cp.location and cp.location.latitude else None,
        "longitude": float(cp.location.longitude) if cp.location and cp.location.longitude else None,
        "created_at": cp.created_at.isoformat() if cp.created_at else None,
    }


@router.get("/stats")
async def admin_stats(
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    today_start = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    cp_res = await db.execute(
        select(ChargePoint).options(selectinload(ChargePoint.location))
    )
    cps = cp_res.scalars().all()

    active_count = (await db.execute(
        select(func.count()).where(ChargeSession.finished_at.is_(None))
    )).scalar_one()

    today_count = (await db.execute(
        select(func.count()).where(ChargeSession.started_at >= today_start)
    )).scalar_one()

    today_energy = (await db.execute(
        select(func.sum(ChargeSession.energy_kwh)).where(
            ChargeSession.started_at >= today_start,
            ChargeSession.energy_kwh.isnot(None),
        )
    )).scalar_one() or 0.0

    today_revenue = (await db.execute(
        select(func.sum(ChargeSession.cost_huf)).where(
            ChargeSession.started_at >= today_start,
            ChargeSession.cost_huf.isnot(None),
        )
    )).scalar_one() or 0.0

    total_sessions = (await db.execute(
        select(func.count(ChargeSession.id))
    )).scalar_one()

    total_energy = (await db.execute(
        select(func.sum(ChargeSession.energy_kwh)).where(ChargeSession.energy_kwh.isnot(None))
    )).scalar_one() or 0.0

    total_revenue = (await db.execute(
        select(func.sum(ChargeSession.cost_huf)).where(ChargeSession.cost_huf.isnot(None))
    )).scalar_one() or 0.0

    statuses = {}
    for cp in cps:
        s = compute_status(cp)
        statuses[s] = statuses.get(s, 0) + 1

    return {
        "charge_points": {"total": len(cps), "by_status": statuses},
        "sessions": {"active": active_count, "today": today_count, "total": total_sessions},
        "energy": {"today_kwh": round(today_energy, 3), "total_kwh": round(total_energy, 3)},
        "revenue": {"today_huf": round(today_revenue), "total_huf": round(total_revenue)},
    }


@router.get("/charge-points")
async def admin_list_charge_points(
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    res = await db.execute(
        select(ChargePoint).options(selectinload(ChargePoint.location))
    )
    return [_cp_dict_admin(cp) for cp in res.scalars().all()]


@router.get("/sessions")
async def admin_list_sessions(
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
    active_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    stmt = (
        select(ChargeSession)
        .options(
            selectinload(ChargeSession.charge_point).selectinload(ChargePoint.location),
            selectinload(ChargeSession.intent),
        )
        .order_by(desc(ChargeSession.started_at), desc(ChargeSession.id))
    )
    if active_only:
        stmt = stmt.where(ChargeSession.finished_at.is_(None))
    stmt = stmt.offset(offset).limit(limit)
    res = await db.execute(stmt)
    return [_session_dict(s) for s in res.scalars().all()]


@router.get("/intents")
async def admin_list_intents(
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    res = await db.execute(
        select(ChargingIntent)
        .options(selectinload(ChargingIntent.charge_point))
        .order_by(desc(ChargingIntent.created_at))
        .offset(offset).limit(limit)
    )
    return [_intent_dict(i) for i in res.scalars().all()]


@router.post("/sessions/{session_id}/stop")
async def admin_stop_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    from app.ocpp.ocpp_ws import remote_stop_transaction

    res = await db.execute(
        select(ChargeSession)
        .options(selectinload(ChargeSession.charge_point))
        .where(ChargeSession.id == session_id)
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    if s.finished_at is not None:
        return {"ok": True, "already_finished": True}
    if not s.ocpp_transaction_id:
        raise HTTPException(status_code=409, detail={"error": "no_ocpp_transaction_id"})

    try:
        ocpp_res = await remote_stop_transaction(
            cp_id=str(s.charge_point.ocpp_id),
            transaction_id=s.ocpp_transaction_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "ocpp_remote_stop_failed", "reason": str(e)})

    if (ocpp_res or {}).get("status") not in ("Accepted", "accepted"):
        raise HTTPException(status_code=409, detail={"error": "remote_stop_rejected", "ocpp": ocpp_res})

    return {"ok": True, "ocpp": ocpp_res}
