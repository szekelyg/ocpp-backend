from fastapi import FastAPI, WebSocket
import logging
from ocpp_ws import handle_ocpp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.websocket("/ocpp")
async def ocpp_no_id(ws: WebSocket):
    # ha a töltő csak simán /ocpp-ra csatlakozik
    logger.info("OCPP kapcsolat érkezett path=/ocpp (nincs ID a path-ban)")
    await handle_ocpp(ws)

@app.websocket("/ocpp/{chargebox_id}")
async def ocpp_with_id(ws: WebSocket, chargebox_id: str):
    # ha a path végére odarakja az ID-t (pl. /ocpp/VLTHU001B)
    logger.info(f"OCPP kapcsolat érkezett path=/ocpp/{chargebox_id}, ID={chargebox_id}")
    await handle_ocpp(ws)