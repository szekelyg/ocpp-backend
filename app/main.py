import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.api.routers.charge_points import router as charge_points_router
from app.api.routers.sessions import router as sessions_router
from app.api.routers.payments_stripe import router as payments_stripe_router
from app.api.routers.intents import router as intents_router
from app.ocpp.ocpp_ws import handle_ocpp

logger = logging.getLogger("backend")
logging.basicConfig(level=logging.INFO)
logging.getLogger("ocpp").setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Waiting session timeout background task
# ---------------------------------------------------------------------------

_WAITING_TIMEOUT_MINUTES = 15
# Ha a töltő ennyi perce nem jelentkezett (last_seen_at), de van nyitott charging session,
# akkor azt lezárjuk (a töltő kiesett, és StopTransaction soha nem érkezett).
_CHARGING_STALE_CP_MINUTES = 30


async def _try_stripe_cancel_or_refund(checkout_session_id: str, charge_session_id: int) -> None:
    """
    Timeout esetén felszabadítja a Stripe zárolást:
    - Ha a PaymentIntent még nincs capture-ölve (requires_capture) → cancel() = zárolás felszabadítás
    - Ha már capture-ölve van (succeeded) → Refund.create() = visszatérítés
    """
    stripe_key = os.environ.get("STRIPE_SECRET_KEY")
    if not stripe_key:
        logger.warning(f"STRIPE_SECRET_KEY not set – skipping Stripe cleanup for session_id={charge_session_id}")
        return

    def _do() -> str:
        import stripe as _stripe
        _stripe.api_key = stripe_key
        cs = _stripe.checkout.Session.retrieve(checkout_session_id)
        pi_id = cs.get("payment_intent")
        if not pi_id:
            logger.warning(f"No payment_intent in checkout session {checkout_session_id}")
            return "no_pi"
        pi = _stripe.PaymentIntent.retrieve(pi_id)
        status = pi.get("status")
        if status == "requires_capture":
            # Csak zárolva volt, még nem vonták le – cancel = azonnali felszabadítás
            _stripe.PaymentIntent.cancel(pi_id)
            logger.info(f"Stripe PI cancelled (timeout): pi={pi_id} session_id={charge_session_id}")
            return "cancelled"
        elif status == "succeeded":
            # Már levonták (nem kellene, de kezeljük) → visszatérítés
            refund = _stripe.Refund.create(payment_intent=pi_id)
            logger.info(f"Stripe refund created: refund_id={refund.get('id')} session_id={charge_session_id}")
            return "refunded"
        else:
            logger.info(f"Stripe PI status={status}, no action needed: pi={pi_id} session_id={charge_session_id}")
            return f"noop:{status}"

    try:
        result = await asyncio.to_thread(_do)
        logger.info(f"Stripe timeout cleanup result={result} session_id={charge_session_id}")
    except Exception:
        logger.exception(f"Stripe timeout cleanup failed for session_id={charge_session_id}")


async def _expire_waiting_sessions_once() -> None:
    from app.db.session import AsyncSessionLocal
    from app.db.models import ChargeSession
    from app.ocpp.time_utils import utcnow
    from app.services.email import send_no_start_email

    cutoff = utcnow() - timedelta(minutes=_WAITING_TIMEOUT_MINUTES)

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(ChargeSession)
            .options(selectinload(ChargeSession.intent))
            .options(selectinload(ChargeSession.charge_point))
            .where(
                and_(
                    ChargeSession.finished_at.is_(None),
                    ChargeSession.ocpp_transaction_id.is_(None),
                    ChargeSession.started_at < cutoff,
                )
            )
        )
        sessions = res.scalars().all()

    for cs in sessions:
        logger.warning(
            f"WaitingTimeout: session_id={cs.id} started_at={cs.started_at} – marking finished"
        )
        async with AsyncSessionLocal() as db:
            from app.db.models import ChargeSession as CS
            from app.ocpp.time_utils import utcnow as _now
            # Re-fetch to avoid detached instance issues
            row = (await db.execute(
                select(CS).options(selectinload(CS.intent)).options(selectinload(CS.charge_point))
                .where(CS.id == cs.id)
            )).scalar_one_or_none()
            if row is None or row.finished_at is not None:
                continue  # already handled
            row.finished_at = _now()
            await db.commit()

        # Stripe refund
        if cs.intent and cs.intent.payment_provider == "stripe" and cs.intent.payment_provider_ref:
            await _try_stripe_cancel_or_refund(cs.intent.payment_provider_ref, cs.id)

        # Email
        if cs.anonymous_email:
            cp_ocpp_id = cs.charge_point.ocpp_id if cs.charge_point else "—"
            await send_no_start_email(
                to=cs.anonymous_email,
                session_id=cs.id,
                cp_ocpp_id=cp_ocpp_id,
            )


async def _expire_stale_charging_sessions_once() -> None:
    """
    Ha egy töltő ennyi perce nem jelentkezett (last_seen_at), de van nyitott charging session
    (ocpp_transaction_id IS NOT NULL, finished_at IS NULL), lezárjuk a sessiont.
    Ez kezeli azt az esetet, amikor a töltő kiesik és StopTransaction soha nem érkezik.
    """
    from app.db.session import AsyncSessionLocal
    from app.db.models import ChargeSession, ChargePoint
    from app.ocpp.time_utils import utcnow
    from app.services.email import send_receipt_email

    cp_cutoff = utcnow() - timedelta(minutes=_CHARGING_STALE_CP_MINUTES)

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(ChargeSession)
            .join(ChargePoint, ChargeSession.charge_point_id == ChargePoint.id)
            .options(selectinload(ChargeSession.charge_point))
            .options(selectinload(ChargeSession.intent))
            .where(
                and_(
                    ChargeSession.finished_at.is_(None),
                    ChargeSession.ocpp_transaction_id.isnot(None),
                    ChargePoint.last_seen_at < cp_cutoff,
                )
            )
        )
        sessions = res.scalars().all()

    for cs in sessions:
        cp_ocpp_id = cs.charge_point.ocpp_id if cs.charge_point else "—"
        logger.warning(
            f"StaleChargingTimeout: session_id={cs.id} cp={cp_ocpp_id} "
            f"started_at={cs.started_at} – töltő {_CHARGING_STALE_CP_MINUTES} perce offline, session lezárása"
        )
        finished_at_val = None
        energy_kwh_val = None
        cost_huf_val = None

        async with AsyncSessionLocal() as db:
            from app.db.models import ChargeSession as CS, ChargePoint as CP
            from app.ocpp.time_utils import utcnow as _now
            from app.ocpp.ocpp_utils import _price_huf_per_kwh
            row = (await db.execute(
                select(CS).where(CS.id == cs.id)
            )).scalar_one_or_none()
            if row is None or row.finished_at is not None:
                continue  # már le lett zárva
            finished_at_val = _now()
            row.finished_at = finished_at_val
            # energy/cost: ha van meter_stop_wh (live update töltötte be), számoljuk ki
            if row.meter_start_wh is not None and row.meter_stop_wh is not None:
                diff = float(row.meter_stop_wh) - float(row.meter_start_wh)
                if diff >= 0:
                    row.energy_kwh = diff / 1000.0
                    energy_kwh_val = row.energy_kwh
            price = _price_huf_per_kwh()
            if price is not None and row.energy_kwh is not None:
                row.cost_huf = float(row.energy_kwh) * float(price)
                cost_huf_val = row.cost_huf
            # CP státusz visszaállítása (ha még charging-en áll)
            cp_row = (await db.execute(select(CP).where(CP.id == row.charge_point_id))).scalar_one_or_none()
            if cp_row and cp_row.status == "charging":
                cp_row.status = "available"
            await db.commit()

        # Stripe capture vagy cancel a tényleges energia alapján
        if cs.intent and cs.intent.payment_provider == "stripe":
            from app.ocpp.handlers.transactions import _stripe_settle as _settle
            # Frissített session objektum szükséges a settle-hez
            async with AsyncSessionLocal() as db2:
                from app.db.models import ChargeSession as CS2
                fresh = (await db2.execute(
                    select(CS2).options(selectinload(CS2.intent)).where(CS2.id == cs.id)
                )).scalar_one_or_none()
                if fresh:
                    await _settle(fresh)

        if cs.anonymous_email and finished_at_val is not None:
            duration_s = None
            if cs.started_at:
                from datetime import timezone as _tz
                s = cs.started_at if cs.started_at.tzinfo else cs.started_at.replace(tzinfo=_tz.utc)
                e = finished_at_val if finished_at_val.tzinfo else finished_at_val.replace(tzinfo=_tz.utc)
                duration_s = max(0, int((e - s).total_seconds()))
            await send_receipt_email(
                to=cs.anonymous_email,
                session_id=cs.id,
                cp_ocpp_id=cp_ocpp_id,
                duration_s=duration_s,
                energy_kwh=energy_kwh_val,
                cost_huf=cost_huf_val,
            )


async def _waiting_timeout_loop() -> None:
    logger.info("WaitingTimeout background task started")
    while True:
        await asyncio.sleep(60)
        try:
            await _expire_waiting_sessions_once()
        except Exception:
            logger.exception("WaitingTimeout task error")
        try:
            await _expire_stale_charging_sessions_once()
        except Exception:
            logger.exception("StaleChargingTimeout task error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    task = asyncio.create_task(_waiting_timeout_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Background tasks stopped")


app = FastAPI(title="OCPP Backend MVP", lifespan=lifespan)

# REST API routerek
app.include_router(charge_points_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(payments_stripe_router, prefix="/api")
app.include_router(intents_router, prefix="/api")


# Ideiglenes admin endpoint – GetConfiguration lekérdezés
@app.get("/api/admin/get-config/{cp_id}")
async def admin_get_config(cp_id: str):
    from app.ocpp.registry import send_call_and_wait
    try:
        res = await send_call_and_wait(cp_id, "GetConfiguration", {}, timeout_s=10)
        return res
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/admin/change-config/{cp_id}")
async def admin_change_config(cp_id: str, key: str, value: str):
    from app.ocpp.registry import send_call_and_wait
    try:
        res = await send_call_and_wait(cp_id, "ChangeConfiguration", {"key": key, "value": value}, timeout_s=10)
        return res
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/api/admin/reset/{cp_id}")
async def admin_reset(cp_id: str, reset_type: str = "Soft"):
    from app.ocpp.registry import send_call_and_wait
    try:
        res = await send_call_and_wait(cp_id, "Reset", {"type": reset_type}, timeout_s=15)
        return res
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# OCPP WebSocket endpoint – ID-val a path-ban
@app.websocket("/ocpp/{charge_point_id}")
async def ocpp_with_id(ws: WebSocket, charge_point_id: str):
    logger.info(f"OCPP kapcsolat érkezett path=/ocpp/{charge_point_id}, ID={charge_point_id}")
    await handle_ocpp(ws, charge_point_id)


# OCPP WebSocket endpoint – ha nincs ID a path-ban
@app.websocket("/ocpp")
async def ocpp_no_id(ws: WebSocket):
    logger.info("OCPP kapcsolat érkezett path=/ocpp (nincs ID a path-ban)")
    await handle_ocpp(ws, None)


# -----------------------------
# Frontend (React build) + SPA fallback
# -----------------------------
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
INDEX_HTML = FRONTEND_DIST / "index.html"

# Csak a /assets/* könyvtárat mountoljuk statikusan (Vite build output)
# A "/" mount html=True módban elnyeli a kéréseket a SPA fallback elől → 404
if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="static-assets")
else:
    logger.warning(f"frontend assets not found at: {FRONTEND_DIST / 'assets'}")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """
    SPA fallback: minden nem-API útvonal index.html-t kap (React Router).
    Egyedi statikus fájlokat (favicon, vite.svg stb.) közvetlenül szolgálunk ki.
    """
    if full_path.startswith(("api/", "ocpp", "test/")):
        raise HTTPException(status_code=404, detail="Not Found")

    # Konkrét statikus fájl (pl. /vite.svg, /favicon.ico)
    static_file = FRONTEND_DIST / full_path
    if static_file.is_file():
        return FileResponse(str(static_file))

    if not INDEX_HTML.exists():
        raise HTTPException(status_code=503, detail="frontend_not_built")

    return FileResponse(str(INDEX_HTML))
