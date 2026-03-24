# app/api/routers/admin.py
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from app.api.routers.charge_points import compute_status

router = APIRouter(prefix="/admin", tags=["admin"])
_security = HTTPBasic()


# ── Auth ─────────────────────────────────────────────────────────────────────

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


# ── Helpers ───────────────────────────────────────────────────────────────────

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
        "meter_start_wh": s.meter_start_wh,
        "meter_stop_wh": s.meter_stop_wh,
        "intent": {
            "id": intent.id,
            "status": intent.status,
            "hold_amount_huf": intent.hold_amount_huf,
            "billing_type": intent.billing_type,
            "billing_name": intent.billing_name,
            "billing_company": intent.billing_company,
            "billing_city": intent.billing_city,
            "billing_country": intent.billing_country,
            "billing_street": intent.billing_street,
            "billing_zip": intent.billing_zip,
            "billing_tax_number": intent.billing_tax_number,
            "payment_provider": intent.payment_provider,
            "stripe_payment_intent_id": intent.stripe_payment_intent_id,
            "payment_provider_ref": intent.payment_provider_ref,
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


async def _load_session(db: AsyncSession, session_id: int) -> ChargeSession:
    res = await db.execute(
        select(ChargeSession)
        .options(
            selectinload(ChargeSession.charge_point).selectinload(ChargePoint.location),
            selectinload(ChargeSession.intent),
        )
        .where(ChargeSession.id == session_id)
    )
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return s


# ── Stats ─────────────────────────────────────────────────────────────────────

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

    total_sessions = (await db.execute(select(func.count(ChargeSession.id)))).scalar_one()

    total_energy = (await db.execute(
        select(func.sum(ChargeSession.energy_kwh)).where(ChargeSession.energy_kwh.isnot(None))
    )).scalar_one() or 0.0

    total_revenue = (await db.execute(
        select(func.sum(ChargeSession.cost_huf)).where(ChargeSession.cost_huf.isnot(None))
    )).scalar_one() or 0.0

    # Hiányzó számlák száma (befejezett, emailes, intenttel, de invoice_number nélkül)
    missing_invoices = (await db.execute(
        select(func.count()).where(
            ChargeSession.finished_at.isnot(None),
            ChargeSession.anonymous_email.isnot(None),
            ChargeSession.intent_id.isnot(None),
            ChargeSession.invoice_number.is_(None),
        )
    )).scalar_one()

    statuses = {}
    for cp in cps:
        s = compute_status(cp)
        statuses[s] = statuses.get(s, 0) + 1

    return {
        "charge_points": {"total": len(cps), "by_status": statuses},
        "sessions": {"active": active_count, "today": today_count, "total": total_sessions},
        "energy": {"today_kwh": round(today_energy, 3), "total_kwh": round(total_energy, 3)},
        "revenue": {"today_huf": round(today_revenue), "total_huf": round(total_revenue)},
        "alerts": {"missing_invoices": missing_invoices},
    }


# ── Charge points ─────────────────────────────────────────────────────────────

@router.get("/charge-points")
async def admin_list_charge_points(
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    res = await db.execute(
        select(ChargePoint).options(selectinload(ChargePoint.location))
    )
    return [_cp_dict_admin(cp) for cp in res.scalars().all()]


@router.post("/charge-points/{cp_id}/reset")
async def admin_reset_cp(
    cp_id: int,
    reset_type: str = Query("Soft", pattern="^(Soft|Hard)$"),
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    from app.ocpp.registry import send_call_and_wait
    res = await db.execute(select(ChargePoint).where(ChargePoint.id == cp_id))
    cp = res.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint not found")
    try:
        result = await send_call_and_wait(cp.ocpp_id, "Reset", {"type": reset_type}, timeout_s=15)
        return {"ok": True, "ocpp": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "ocpp_failed", "reason": str(e)})


@router.get("/charge-points/{cp_id}/config")
async def admin_get_cp_config(
    cp_id: int,
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    from app.ocpp.registry import send_call_and_wait
    res = await db.execute(select(ChargePoint).where(ChargePoint.id == cp_id))
    cp = res.scalar_one_or_none()
    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint not found")
    try:
        result = await send_call_and_wait(cp.ocpp_id, "GetConfiguration", {}, timeout_s=15)
        return {"ok": True, "config": result}
    except Exception as e:
        raise HTTPException(status_code=502, detail={"error": "ocpp_failed", "reason": str(e)})


# ── Sessions ──────────────────────────────────────────────────────────────────

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


@router.post("/sessions/{session_id}/stop")
async def admin_stop_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    """OCPP RemoteStop – töltő online kell hozzá."""
    from app.ocpp.ocpp_ws import remote_stop_transaction
    s = await _load_session(db, session_id)
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


@router.post("/sessions/{session_id}/force-close")
async def admin_force_close_session(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    """
    Kényszer lezárás OCPP nélkül – ha a töltő offline és StopTransaction soha nem érkezik.
    Energia/díj újraszámolva ha vannak mérőadatok. Stripe settle automatikusan fut.
    """
    from app.ocpp.handlers.transactions import _recalc_energy_and_cost, _stripe_settle

    s = await _load_session(db, session_id)
    if s.finished_at is not None:
        return {"ok": True, "already_finished": True, "session": _session_dict(s)}

    s.finished_at = _utcnow()
    _recalc_energy_and_cost(s)
    await db.commit()
    await db.refresh(s)

    # Stripe settle (capture/cancel) – nem dob kivételt, csak logol
    await _stripe_settle(s)

    return {"ok": True, "session": _session_dict(s)}


@router.post("/sessions/{session_id}/resend-receipt")
async def admin_resend_receipt(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    """Bizonylat email újraküldése a vevőnek."""
    from app.services.email import send_receipt_email
    s = await _load_session(db, session_id)

    if not s.anonymous_email:
        raise HTTPException(status_code=409, detail={"error": "no_email", "hint": "Ennek a sessionnek nincs email-címe."})

    cp_ocpp_id = s.charge_point.ocpp_id if s.charge_point else "—"
    intent = s.intent
    duration_s = _duration_s(s) if s.finished_at else None

    ok = await send_receipt_email(
        to=s.anonymous_email,
        session_id=s.id,
        cp_ocpp_id=cp_ocpp_id,
        duration_s=duration_s,
        energy_kwh=s.energy_kwh,
        cost_huf=s.cost_huf,
        billing_name=intent.billing_name if intent else None,
        billing_type=intent.billing_type if intent else None,
        billing_company=intent.billing_company if intent else None,
        billing_tax_number=intent.billing_tax_number if intent else None,
        billing_street=intent.billing_street if intent else None,
        billing_zip=intent.billing_zip if intent else None,
        billing_city=intent.billing_city if intent else None,
        billing_country=intent.billing_country if intent else None,
    )
    if not ok:
        raise HTTPException(status_code=502, detail={"error": "email_send_failed", "hint": "Ellenőrizd a RESEND_API_KEY-t a logban."})
    return {"ok": True, "sent_to": s.anonymous_email}


@router.post("/sessions/{session_id}/resend-invoice")
async def admin_resend_invoice(
    session_id: int,
    force: bool = Query(False, description="Ha már van invoice_number, új számlát állít ki"),
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    """
    Számla kiállítása és küldése számlázz.hu-n keresztül.
    Ha már van invoice_number és force=False, hibát ad vissza.
    force=True esetén új számlát állít ki (pl. ha az előző sikertelen volt).
    """
    from app.services.invoice import create_session_invoice
    from app.ocpp.handlers.transactions import _captured_amount

    s = await _load_session(db, session_id)

    if not s.anonymous_email:
        raise HTTPException(status_code=409, detail={"error": "no_email"})
    if not s.intent:
        raise HTTPException(status_code=409, detail={"error": "no_intent", "hint": "Nincs fizetési intent ehhez a sessionhöz."})
    if s.is_active if hasattr(s, 'is_active') else s.finished_at is None:
        raise HTTPException(status_code=409, detail={"error": "session_still_active"})
    if s.invoice_number and not force:
        raise HTTPException(status_code=409, detail={
            "error": "invoice_already_exists",
            "invoice_number": s.invoice_number,
            "hint": "Add meg a force=true query paramétert új számla kiállításához.",
        })

    captured_huf = _captured_amount(s)
    if not captured_huf or captured_huf <= 0:
        raise HTTPException(status_code=409, detail={"error": "zero_amount", "hint": "0 Ft-ra nem állítható ki számla."})

    cp_ocpp_id = s.charge_point.ocpp_id if s.charge_point else "—"
    intent = s.intent

    invoice_number = await create_session_invoice(
        session_id=s.id,
        energy_kwh=s.energy_kwh,
        captured_huf=captured_huf,
        cp_ocpp_id=cp_ocpp_id,
        buyer_email=s.anonymous_email,
        buyer_name=intent.billing_name,
        buyer_zip=intent.billing_zip,
        buyer_city=intent.billing_city,
        buyer_street=intent.billing_street,
        buyer_country=intent.billing_country,
        buyer_tax_number=intent.billing_tax_number,
        buyer_company=intent.billing_company,
        billing_type=intent.billing_type,
    )

    if not invoice_number:
        raise HTTPException(status_code=502, detail={"error": "invoice_create_failed", "hint": "Ellenőrizd a SZAMLAZZ_AGENT_KEY-t és a logot."})

    # Mentjük az invoice_number-t
    s.invoice_number = invoice_number
    await db.commit()

    return {"ok": True, "invoice_number": invoice_number, "sent_to": s.anonymous_email}


@router.post("/sessions/{session_id}/stripe-settle")
async def admin_stripe_settle(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    """
    Manuális Stripe capture/cancel – ha a töltés végén a settle nem futott le.
    Lezárt sessionre futtatható.
    """
    from app.ocpp.handlers.transactions import _stripe_settle
    s = await _load_session(db, session_id)
    if s.finished_at is None:
        raise HTTPException(status_code=409, detail={"error": "session_still_active", "hint": "Csak lezárt sessionre futtatható."})
    if not s.intent or not s.intent.stripe_payment_intent_id:
        raise HTTPException(status_code=409, detail={"error": "no_stripe_intent"})
    await _stripe_settle(s)
    return {"ok": True, "pi_id": s.intent.stripe_payment_intent_id}


# ── Intents ───────────────────────────────────────────────────────────────────

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


@router.post("/intents/{intent_id}/refund")
async def admin_refund_intent(
    intent_id: int,
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    """
    Azonnali Stripe visszatérítés/felszabadítás egy intentre.
    - requires_capture → cancel (zárolás felszabadítás)
    - succeeded → refund (tényleges visszautalás)
    """
    import stripe as _stripe

    res = await db.execute(
        select(ChargingIntent).where(ChargingIntent.id == intent_id)
    )
    intent = res.scalar_one_or_none()
    if not intent:
        raise HTTPException(status_code=404, detail="Intent not found")
    if not intent.stripe_payment_intent_id:
        raise HTTPException(status_code=409, detail={"error": "no_stripe_pi"})

    sk = os.environ.get("STRIPE_SECRET_KEY")
    if not sk:
        raise HTTPException(status_code=503, detail={"error": "no_stripe_key"})

    _stripe.api_key = sk
    pi_id = intent.stripe_payment_intent_id

    try:
        pi = _stripe.PaymentIntent.retrieve(pi_id)
        pi_status = pi.get("status")

        if pi_status == "requires_capture":
            _stripe.PaymentIntent.cancel(pi_id)
            action = "cancelled"
        elif pi_status == "succeeded":
            refund = _stripe.Refund.create(payment_intent=pi_id)
            action = f"refunded (refund_id={refund.get('id')})"
        elif pi_status == "canceled":
            return {"ok": True, "action": "already_cancelled", "pi_status": pi_status}
        else:
            raise HTTPException(status_code=409, detail={
                "error": "unexpected_pi_status",
                "pi_status": pi_status,
                "hint": f"Stripe PI státusz: {pi_status}. Manuálisan ellenőrizd a Stripe dashboardon.",
            })
    except _stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail={"error": "stripe_error", "reason": str(e)})

    return {"ok": True, "action": action, "pi_id": pi_id}


# ── Search ────────────────────────────────────────────────────────────────────

@router.get("/search")
async def admin_search(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
    _: HTTPBasicCredentials = Depends(verify_admin),
):
    """
    Keresés email, session ID, invoice szám, OCPP ID alapján.
    """
    q = q.strip()

    # Session ID keresés
    sessions = []
    if q.isdigit():
        res = await db.execute(
            select(ChargeSession)
            .options(
                selectinload(ChargeSession.charge_point).selectinload(ChargePoint.location),
                selectinload(ChargeSession.intent),
            )
            .where(ChargeSession.id == int(q))
        )
        sessions = res.scalars().all()

    # Email / invoice szám keresés
    if not sessions:
        res = await db.execute(
            select(ChargeSession)
            .options(
                selectinload(ChargeSession.charge_point).selectinload(ChargePoint.location),
                selectinload(ChargeSession.intent),
            )
            .where(or_(
                ChargeSession.anonymous_email.ilike(f"%{q}%"),
                ChargeSession.invoice_number.ilike(f"%{q}%"),
            ))
            .order_by(desc(ChargeSession.started_at))
            .limit(50)
        )
        sessions = res.scalars().all()

    # Intent keresés emailre
    res2 = await db.execute(
        select(ChargingIntent)
        .options(selectinload(ChargingIntent.charge_point))
        .where(ChargingIntent.anonymous_email.ilike(f"%{q}%"))
        .order_by(desc(ChargingIntent.created_at))
        .limit(20)
    )
    intents = res2.scalars().all()

    # Töltő OCPP ID keresés
    res3 = await db.execute(
        select(ChargePoint)
        .options(selectinload(ChargePoint.location))
        .where(ChargePoint.ocpp_id.ilike(f"%{q}%"))
        .limit(10)
    )
    cps = res3.scalars().all()

    return {
        "query": q,
        "sessions": [_session_dict(s) for s in sessions],
        "intents": [_intent_dict(i) for i in intents],
        "charge_points": [_cp_dict_admin(cp) for cp in cps],
    }
