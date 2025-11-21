from fastapi import FastAPI, WebSocket
import logging
from app.ocpp.ocpp_ws import handle_ocpp

logger = logging.getLogger("backend")

app = FastAPI()

@app.websocket("/ocpp/{charge_point_id}")
async def ocpp_with_id(ws: WebSocket, charge_point_id: str):
    logger.info(f"OCPP kapcsolat érkezett path=/ocpp/{charge_point_id}, ID={charge_point_id}")
    await handle_ocpp(ws, charge_point_id)

@app.websocket("/ocpp")
async def ocpp_no_id(ws: WebSocket):
    logger.info("OCPP kapcsolat érkezett path=/ocpp (nincs ID a path-ban)")
    # itt None-t adunk, a handler majd kiszedi az ID-t a payloadból
    await handle_ocpp(ws, None)