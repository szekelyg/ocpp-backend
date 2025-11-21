from fastapi import FastAPI, WebSocket
import logging
from app.ocpp.ocpp_ws import handle_ocpp
from app.api.test_db import router as test_db_router


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

app = FastAPI()

app.include_router(test_db_router, prefix="/test")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.websocket("/ocpp")
async def ocpp_no_id(ws: WebSocket):
    # ha a töltő csak simán /ocpp-ra csatlakozik
    logger.info("OCPP kapcsolat érkezett path=/ocpp (nincs ID a path-ban)")
    await handle_ocpp(ws)

@app.websocket("/ocpp/{charge_point_id}")
async def ocpp_endpoint(websocket: WebSocket, charge_point_id: str):
    logger.info(f"OCPP kapcsolat érkezett path=/ocpp/{charge_point_id}, ID={charge_point_id}")
    await handle_ocpp(websocket, charge_point_id)