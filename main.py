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
async def ocpp_endpoint(ws: WebSocket):
    await handle_ocpp(ws)