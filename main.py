from fastapi import FastAPI, WebSocket
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ocpp-test")

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.websocket("/ocpp")
async def ocpp_ws(ws: WebSocket):
    await ws.accept()
    logger.info("Új OCPP kapcsolat érkezett")
    try:
        while True:
            msg = await ws.receive_text()
            logger.info(f"Üzenet: {msg}")
            # egyelőre csak visszaküldjük, hogy lásd, működik a kör
            await ws.send_text(f"echo: {msg}")
    except Exception as e:
        logger.info(f"Kapcsolat lezárult: {e}")
        await ws.close()
