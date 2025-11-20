import logging
from fastapi import WebSocket

logger = logging.getLogger("ocpp")

async def handle_ocpp(ws: WebSocket):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

    try:
        while True:
            msg = await ws.receive_text()
            logger.info(f"OCPP üzenet: {msg}")
            await ws.send_text(f"echo: {msg}")
    except Exception as e:
        logger.info(f"OCPP kapcsolat bezárt: {e}")
        await ws.close()