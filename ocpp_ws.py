import logging
import json
from datetime import datetime, timezone

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger("ocpp")


async def handle_ocpp(ws: WebSocket):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

    try:
        while True:
            text = await ws.receive_text()
            logger.info(f"OCPP RAW: {text}")

            # próbáljuk JSON-ként értelmezni
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Nem JSON, ignorálom")
                continue

            # OCPP 1.6 frame: [msgTypeId, uniqueId, action, payload]
            if not isinstance(msg, list) or len(msg) < 3:
                logger.warning("Nem OCPP frame, ignorálom")
                continue

            msg_type = msg[0]
            msg_id = msg[1]
            action = msg[2]

            # 2 = CALL (töltő → szerver)
            if msg_type == 2 and action == "BootNotification":
                logger.info("BootNotification érkezett")

                now = datetime.now(timezone.utc).isoformat()

                response = [
                    3,          # CALLRESULT
                    msg_id,     # ugyanaz az ID, mint a kérésben
                    {
                        "status": "Accepted",
                        "currentTime": now,
                        "interval": 60,   # másodperc – ennyi időnként Heartbeat
                    },
                ]

                await ws.send_text(json.dumps(response))
                logger.info(f"BootNotification válasz elküldve: {response}")

            else:
                logger.info(f"Nem kezelt OCPP üzenet: {action}")

    except WebSocketDisconnect as e:
        logger.info(f"OCPP kapcsolat bezárt: {e}")
    except Exception as e:
        logger.exception(f"Váratlan hiba OCPP kapcsolatban: {e}")