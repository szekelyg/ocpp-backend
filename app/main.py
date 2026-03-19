import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import text

from app.api.deps import get_db
from app.api.routers.charge_points import router as charge_points_router
from app.api.routers.sessions import router as sessions_router
from app.api.routers.payments_stripe import router as payments_stripe_router
from app.api.routers.intents import router as intents_router
from app.ocpp.ocpp_ws import handle_ocpp

logger = logging.getLogger("backend")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Waiting session timeout background task
# ---------------------------------------------------------------------------

_WAITING_TIMEOUT_MINUTES = 15


async def _try_stripe_refund(checkout_session_id: str, charge_session_id: int) -> None:
    """Refund the Stripe payment for a timed-out session (runs in thread pool)."""
    stripe_key = os.environ.get("STRIPE_SECRET_KEY")
    if not stripe_key:
        logger.warning(f"STRIPE_SECRET_KEY not set – skipping refund for session_id={charge_session_id}")
        return

    def _do() -> str | None:
        import stripe as _stripe
        _stripe.api_key = stripe_key
        cs = _stripe.checkout.Session.retrieve(checkout_session_id)
        pi_id = cs.get("payment_intent")
        if not pi_id:
            logger.warning(f"No payment_intent in checkout session {checkout_session_id}")
            return None
        refund = _stripe.Refund.create(payment_intent=pi_id)
        return refund.get("id")

    try:
        refund_id = await asyncio.to_thread(_do)
        if refund_id:
            logger.info(f"Stripe refund created: refund_id={refund_id} session_id={charge_session_id}")
    except Exception:
        logger.exception(f"Stripe refund failed for session_id={charge_session_id}")


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
            await _try_stripe_refund(cs.intent.payment_provider_ref, cs.id)

        # Email
        if cs.anonymous_email:
            cp_ocpp_id = cs.charge_point.ocpp_id if cs.charge_point else "—"
            await send_no_start_email(
                to=cs.anonymous_email,
                session_id=cs.id,
                cp_ocpp_id=cp_ocpp_id,
            )


async def _waiting_timeout_loop() -> None:
    logger.info("WaitingTimeout background task started")
    while True:
        await asyncio.sleep(60)
        try:
            await _expire_waiting_sessions_once()
        except Exception:
            logger.exception("WaitingTimeout task error")


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


@app.get("/test/db-test")
async def db_test(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("SELECT 1"))
    value = result.scalar_one()
    return {"db": value}


@app.get("/test/ping")
async def ping():
    return {"status": "ok"}


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
