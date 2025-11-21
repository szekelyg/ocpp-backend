import logging
import json

from datetime import datetime
from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select

logger = logging.getLogger("ocpp")


async def handle_ocpp(ws: WebSocket, charge_point_id: str):
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
            payload = msg[3] if len(msg) > 3 and isinstance(msg[3], dict) else {}

            # MINDEN timestamp UTC naiv (!) a DB miatt
            now_dt = datetime.utcnow()

            # 2 = CALL (töltő → szerver)
            if msg_type == 2 and action == "BootNotification":
                logger.info("BootNotification érkezett")
                vendor = payload.get("chargePointVendor")
                model = payload.get("chargePointModel")
                serial = payload.get("chargePointSerialNumber")
                fw = payload.get("firmwareVersion")

                # DB: charge_point upsert
                try:
                    async with AsyncSessionLocal() as session:
                        cp = await session.execute(
                            select(ChargePoint).where(ChargePoint.ocpp_id == charge_point_id)
                        )
                        cp = cp.scalar_one_or_none()

                        if cp is None:
                            cp = ChargePoint(
                                ocpp_id=charge_point_id,
                                vendor=vendor,
                                model=model,
                                serial_number=serial,
                                firmware_version=fw,
                                status="available",
                                last_seen_at=now_dt,
                            )
                            session.add(cp)
                            logger.info(f"Új ChargePoint létrehozva DB-ben: {charge_point_id}")
                        else:
                            cp.vendor = vendor
                            cp.model = model
                            cp.serial_number = serial
                            cp.firmware_version = fw
                            cp.status = "available"
                            cp.last_seen_at = now_dt
                            logger.info(f"ChargePoint frissítve DB-ben: {charge_point_id}")

                        await session.commit()
                except Exception as e:
                    logger.exception(f"Hiba a ChargePoint mentésekor: {e}")

                # OCPP válasz is lehet UTC naiv → stringként mehet
                now_str = now_dt.isoformat()

                response = [
                    3,
                    msg_id,
                    {
                        "status": "Accepted",
                        "currentTime": now_str,
                        "interval": 60,
                    },
                ]
                await ws.send_text(json.dumps(response))
                logger.info(f"BootNotification válasz elküldve: {response}")

            elif msg_type == 2 and action == "StatusNotification":
                logger.info("StatusNotification érkezett")

                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))
                logger.info(f"StatusNotification válasz elküldve: {response}")

            elif msg_type == 2 and action == "Heartbeat":
                logger.info("Heartbeat érkezett")

                now_str = now_dt.isoformat()

                response = [3, msg_id, {"currentTime": now_str}]
                await ws.send_text(json.dumps(response))
                logger.info(f"Heartbeat válasz elküldve: {response}")

            elif msg_type == 2 and action == "MeterValues":
                logger.info("MeterValues érkezett")

                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))
                logger.info(f"MeterValues válasz elküldve: {response}")

            else:
                logger.info(f"Nem kezelt OCPP üzenet: {action}")

    except WebSocketDisconnect as e:
        logger.info(f"OCPP kapcsolat bezárt: {e}")
    except Exception as e:
        logger.exception(f"Váratlan hiba OCPP kapcsolatban: {e}")