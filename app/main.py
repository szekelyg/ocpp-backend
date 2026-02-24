import logging

from fastapi import FastAPI, Depends, WebSocket
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.api.deps import get_db
from app.api.routers.charge_points import router as charge_points_router
from app.api.routers.sessions import router as sessions_router
from app.ocpp.ocpp_ws import handle_ocpp
from app.api.routers.payments_stripe import router as payments_stripe_router
from app.api.routers.intents import router as intents_router


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


# Frontend (React build) – TEDD A VÉGÉRE
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="frontend")