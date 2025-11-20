import logging
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger("ocpp")

async def handle_ocpp(ws: WebSocket):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

    try:
        while True:
            msg = await ws.receive_text()
            logger.info(f"OCPP üzenet: {msg}")
            # FONTOS: egyelőre SEMMIT nem küldünk vissza a töltőnek
            # csak logolunk, hogy lássuk, milyen OCPP frame-ek jönnek
    except WebSocketDisconnect as e:
        logger.info(f"OCPP kapcsolat bezárt: {e}")
        # itt NEM hívunk ws.close()-t, mert már eleve bezáródott
    except Exception as e:
        logger.exception(f"Váratlan hiba OCPP kapcsolatban: {e}")