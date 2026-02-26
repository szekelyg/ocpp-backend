import logging
import os
from pathlib import Path

from fastapi import FastAPI, Depends, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.api.deps import get_db
from app.api.routers.charge_points import router as charge_points_router
from app.api.routers.sessions import router as sessions_router
from app.api.routers.payments_stripe import router as payments_stripe_router
from app.api.routers.intents import router as intents_router
from app.ocpp.ocpp_ws import handle_ocpp

logger = logging.getLogger("backend")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="OCPP Backend MVP")

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

# statikus assetek (Vite build: /assets/*)
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=False, name="frontend-static"))
else:
    logger.warning(f"frontend dist not found at: {FRONTEND_DIST}")


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """
    SPA fallback: minden NEM /api és NEM /ocpp és NEM /test útvonal index.html-t kap.
    Így a React Router (pl. /pay/success) nem 404.
    """
    # backend route-ok kizárása
    if full_path.startswith(("api/", "ocpp", "test/")):
        # itt direkt 404 (ne nyelje le)
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not Found")

    if not INDEX_HTML.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="frontend_not_built")

    return FileResponse(str(INDEX_HTML))