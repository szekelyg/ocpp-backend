import logging
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

logger = logging.getLogger("ocpp")

async def handle_ocpp(ws: WebSocket):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

    try:
        while True:
            message = await ws.receive()   # nyers ASGI üzenet
            msg_type = message.get("type")

            if msg_type == "websocket.receive":
                if "text" in message and message["text"] is not None:
                    logger.info(f"OCPP TEXT üzenet: {message['text']}")
                elif "bytes" in message and message["bytes"] is not None:
                    logger.info(f"OCPP BYTES üzenet (hossz={len(message['bytes'])})")
                else:
                    logger.info(f"OCPP ismeretlen receive: {message}")
            elif msg_type == "websocket.disconnect":
                code = message.get("code")
                logger.info(f"OCPP kapcsolat bontva, kód: {code}")
                break
            else:
                logger.info(f"OCPP egyéb üzenet: {message}")
    except WebSocketDisconnect as e:
        logger.info(f"OCPP kapcsolat bezárt: {e}")
    except Exception as e:
        logger.exception(f"Váratlan hiba OCPP kapcsolatban: {e}")