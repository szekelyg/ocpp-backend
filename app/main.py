import logging
import os
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
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
