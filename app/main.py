import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, select, update
from sqlalchemy.orm import selectinload

from app.api.routers.charge_points import router as charge_points_router
from app.api.routers.sessions import router as sessions_router
from app.api.routers.payments_stripe import router as payments_stripe_router
from app.api.routers.intents import router as intents_router
from app.api.routers.admin import router as admin_router
from app.api.routers.auth import router as auth_router
from app.api.routers.me import router as me_router
from app.api.routers.integration import router as integration_router
from app.core.cors import PathScopedCORS, portal_origins
from app.core.rate_limit import RateLimitMiddleware
from app.ocpi.router import router as ocpi_router
from app.ocpi.errors import add_ocpi_exception_handlers
from app.ocpp.ocpp_ws import handle_ocpp
# A függő (kifizetett, el nem indult) munkamenet lejárata – közös forrás: pending_start
from app.ocpp.handlers.pending_start import WAITING_TIMEOUT_MINUTES as _WAITING_TIMEOUT_MINUTES

logger = logging.getLogger("backend")
logging.basicConfig(level=logging.INFO)
logging.getLogger("ocpp").setLevel(logging.DEBUG)

# ---------------------------------------------------------------------------
# Waiting session timeout background task
# ---------------------------------------------------------------------------

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
    """Kifizetett, el nem indult munkamenetek az ablak (WAITING_TIMEOUT_MINUTES) lejárta után.

    - a töltő online → lezárás + zárolás feloldása + „nem indult el” e-mail (eddigi viselkedés);
    - a töltő offline → offline-ra vár (offline_wait_since), a zárolás marad, e-mail nem megy:
      a töltés net nélkül is folyhat, a StartTransaction visszacsatlakozáskor jön (pending_start.py);
    - offline-ra váró munkamenet → lezárás + feloldás, ha a töltő visszajött, de RECONNECT_GRACE_S
      alatt nem jött StartTransaction, vagy ha letelt az OFFLINE_WAIT_MAX_HOURS a fizetéstől.
    """
    from app.db.session import AsyncSessionLocal
    from app.db.models import ChargeSession
    from app.ocpp import registry
    from app.ocpp.handlers import pending_start as ps
    from app.ocpp.time_utils import utcnow

    now = utcnow()
    cutoff = now - timedelta(minutes=_WAITING_TIMEOUT_MINUTES)

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
        cp = cs.charge_point
        cp_ocpp_id = cp.ocpp_id if cp else "—"

        if cs.offline_wait_since is None:
            if cp is not None and await ps.charger_offline(cp):
                if await _set_offline_wait(cs.id, now):
                    logger.warning(
                        f"OfflineWait: session_id={cs.id} cp={cp_ocpp_id} – lejárt az ablak, a töltő offline: "
                        f"offline-ra vár, a zárolás marad (legkésőbb {ps.offline_wait_deadline(cs).isoformat()})"
                    )
                continue
            logger.warning(
                f"WaitingTimeout: session_id={cs.id} started_at={cs.started_at} – marking finished"
            )
            await _close_not_started(cs)
            continue

        # Offline-ra vár: letelt a felső határ?
        if now >= ps.offline_wait_deadline(cs):
            if await _close_not_started(cs, reason=(
                f"A töltővel megszakadt a kapcsolat, és {ps.OFFLINE_WAIT_MAX_HOURS} órán belül nem lett "
                f"újra elérhető, ezért a munkamenetet lezártuk. A zárolt összeget nem terheljük."
            )):
                logger.warning(
                    f"OfflineWait lejárt: session_id={cs.id} cp={cp_ocpp_id} – {ps.OFFLINE_WAIT_MAX_HOURS} óra "
                    f"alatt nem jött StartTransaction: lezárva, zárolás feloldva"
                )
            continue

        # Visszajött a töltő, és a türelmi idő alatt sem jött StartTransaction → nem indult el
        back = await registry.connected_since(cp_ocpp_id) if cp else None
        if (back is not None and not await ps.charger_offline(cp)
                and now - back >= timedelta(seconds=ps.RECONNECT_GRACE_S)):
            if await _close_not_started(cs, reason=(
                "A töltővel megszakadt a kapcsolat. Amikor újra elérhető lett, nem jelezte, hogy a "
                "töltés elindult, ezért a munkamenetet lezártuk."
            )):
                logger.warning(
                    f"OfflineWait: session_id={cs.id} cp={cp_ocpp_id} – visszajött ({back.isoformat()}), "
                    f"de {ps.RECONNECT_GRACE_S} mp alatt nem jött StartTransaction: nem indult el, "
                    f"lezárva, zárolás feloldva"
                )


async def _set_offline_wait(session_id: int, now) -> bool:
    """Offline-ra vár jelölés – csak ha közben nem indult el és nem zárult le."""
    from app.db.session import AsyncSessionLocal
    from app.db.models import ChargeSession
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            update(ChargeSession)
            .where(and_(ChargeSession.id == session_id, ChargeSession.finished_at.is_(None),
                        ChargeSession.ocpp_transaction_id.is_(None)))
            .values(offline_wait_since=now)
        )
        await db.commit()
        return res.rowcount == 1


async def _close_not_started(cs, reason: Optional[str] = None) -> bool:
    """El nem indult munkamenet lezárása + Stripe-zárolás feloldása + „nem indult el” e-mail.
    Feltételes: ha közben megjött a StartTransaction vagy lezárták, nem csinál semmit (False)."""
    from app.db.session import AsyncSessionLocal
    from app.db.models import ChargeSession
    from app.ocpp.time_utils import utcnow
    from app.services.email import send_no_start_email

    async with AsyncSessionLocal() as db:
        res = await db.execute(
            update(ChargeSession)
            .where(and_(ChargeSession.id == cs.id, ChargeSession.finished_at.is_(None),
                        ChargeSession.ocpp_transaction_id.is_(None)))
            .values(finished_at=utcnow())
        )
        await db.commit()
        if res.rowcount != 1:
            return False  # már elindult vagy lezárták

    # Stripe: zárolás feloldása
    if cs.intent and cs.intent.payment_provider == "stripe" and cs.intent.payment_provider_ref:
        await _try_stripe_cancel_or_refund(cs.intent.payment_provider_ref, cs.id)

    # Email
    if cs.anonymous_email:
        cp_ocpp_id = cs.charge_point.ocpp_id if cs.charge_point else "—"
        await send_no_start_email(
            to=cs.anonymous_email,
            session_id=cs.id,
            cp_ocpp_id=cp_ocpp_id,
            reason=reason,
        )
    return True


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
            from app.ocpp.ocpp_utils import effective_price_huf_per_kwh
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
            # ár: per-intent override (admin teszt), ha van; cs.intent be van töltve (selectinload)
            price = effective_price_huf_per_kwh(cs.intent)
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

        # OCPI: CDR pillanatkép a (kiesés miatt) lezárt töltésről is (best-effort)
        if finished_at_val is not None:
            from app.ocpi.services.cdr_service import snapshot_session_cdr
            await snapshot_session_cdr(cs.id)


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


# Kimaradt számlák pótlása – ha a Számlázz.hu a töltés végén nem volt elérhető.
_INVOICE_RETRY_INTERVAL_S = int(os.environ.get("INVOICE_RETRY_INTERVAL_S", "600"))


async def _invoice_retry_loop() -> None:
    from app.services.invoice_retry import retry_missing_invoices_once
    logger.info("InvoiceRetry background task started")
    while True:
        await asyncio.sleep(_INVOICE_RETRY_INTERVAL_S)
        try:
            fixed = await retry_missing_invoices_once()
            if fixed:
                logger.info(f"InvoiceRetry: {fixed} számla pótolva")
        except Exception:
            logger.exception("InvoiceRetry task error")


async def _load_balance_loop() -> None:
    """Terheléselosztás ellenőrző kör: percenként újraszámol, és csak eltérésnél küld
    (elveszett StartTransaction/StopTransaction, újraindult töltő, admin-módosítás)."""
    from app.services.load_balance import rebalance_all
    await asyncio.sleep(10)
    while True:
        await rebalance_all("periodic")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    tasks = [
        asyncio.create_task(_waiting_timeout_loop()),
        asyncio.create_task(_invoice_retry_loop()),
        asyncio.create_task(_load_balance_loop()),
    ]
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.info("Background tasks stopped")


def _api_docs_enabled() -> bool:
    """FastAPI automatikus dokumentáció (/docs, /redoc, /openapi.json) – élesben KI.

    A teljes API-térkép (admin végpontok, paraméterek) nem publikus; fejlesztéshez
    ENABLE_API_DOCS=1 kapcsolja be (pl. deploy/.env.dev).
    """
    return (os.environ.get("ENABLE_API_DOCS") or "").strip().lower() in ("1", "true", "yes")


_DOCS = _api_docs_enabled()
app = FastAPI(
    title="OCPP Backend MVP",
    lifespan=lifespan,
    docs_url="/docs" if _DOCS else None,
    redoc_url="/redoc" if _DOCS else None,
    openapi_url="/openapi.json" if _DOCS else None,
)

# REST API routerek
app.include_router(charge_points_router, prefix="/api")
app.include_router(sessions_router, prefix="/api")
app.include_router(payments_stripe_router, prefix="/api")
app.include_router(intents_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(me_router, prefix="/api")
app.include_router(integration_router, prefix="/api")

# CORS csak a /api/me/* útvonalon, a portál (my.energiafelho.hu) originjére: Bearer token,
# cookie nélkül (allow_credentials=False). A többi végpont CORS-viselkedése változatlan.
app.add_middleware(
    PathScopedCORS,
    path_prefix="/api/me",
    allow_origins=portal_origins(),
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["Authorization", "Accept", "Content-Type"],
    allow_credentials=False,
    max_age=600,
)

# Rate limit a publikus végpontokon (app/core/rate_limit.py) – a legkülső réteg, hogy a
# korlátozott kérés semmilyen munkát ne okozzon.
app.add_middleware(RateLimitMiddleware)

# OCPI 2.2.1 (CPO role) – own "/ocpi" prefix, sibling of "/api"
app.include_router(ocpi_router)
add_ocpi_exception_handlers(app)


# Megjegyzés: a GetConfiguration / ChangeConfiguration / Reset admin műveletek
# a hitelesített admin routerben élnek (app/api/routers/admin.py):
#   POST /api/admin/charge-points/{id}/reset
#   GET  /api/admin/charge-points/{id}/config
# A korábbi top-level /api/admin/{reset,get-config,change-config} végpontok
# hitelesítés NÉLKÜL voltak elérhetők (bárki újraindíthatott egy töltőt) – eltávolítva.


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
    if full_path.startswith(("api/", "ocpp", "ocpi", "test/")):
        raise HTTPException(status_code=404, detail="Not Found")
    # Kikapcsolt API-dokumentáció: valódi 404, ne az SPA index.html-je (200)
    if full_path.rstrip("/") in ("docs", "redoc", "openapi.json", "docs/oauth2-redirect"):
        raise HTTPException(status_code=404, detail="Not Found")

    # Konkrét statikus fájl (pl. /vite.svg, /favicon.ico)
    static_file = FRONTEND_DIST / full_path
    if static_file.is_file():
        return FileResponse(str(static_file))

    if not INDEX_HTML.exists():
        raise HTTPException(status_code=503, detail="frontend_not_built")

    return FileResponse(str(INDEX_HTML))
