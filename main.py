from fastapi import FastAPI, WebSocket
import logging
from ocpp_ws import handle_ocpp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

# FONTOS: itt fogadjuk a /ocpp/{chargebox_id} útvonalat is
@app.websocket("/ocpp/{chargebox_id}")
async def ocpp_endpoint(ws: WebSocket, chargebox_id: str):
    logger.info(f"OCPP kapcsolat érkezett: {chargebox_id}")
    await handle_ocpp(ws)