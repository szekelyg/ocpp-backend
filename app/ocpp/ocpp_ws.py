import logging
import json
from datetime import datetime

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint

logger = logging.getLogger("ocpp")


async def handle_ocpp(ws: WebSocket, charge_point_id: str | None = None):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

    try:
        while True:
            text = await ws.receive_text()
            logger.info(f"OCPP RAW: {text}")

            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Nem JSON, ignorálom")
                continue

            if not isinstance(msg, list) or len(msg) < 3:
                logger.warning("Nem OCPP frame, ignorálom")
                continue

            msg_type = msg[0]
            msg_id = msg[1]
            action = msg[2]
            payload = msg[3] if len(msg) > 3 and isinstance(msg[3], dict) else {}

            if msg_type == 2 and action == "BootNotification":
                logger.info("BootNotification érkezett")

                # ha nincs path ID, vegyük a payloadból
                cp_id = (
                    charge_point_id
                    or payload.get("chargeBoxSerialNumber")
                    or payload.get("chargePointSerialNumber")
                    or "UNKNOWN"
                )

                vendor = payload.get("chargePointVendor")
                model = payload.get("chargePointModel")
                serial = payload.get("chargePointSerialNumber")
                fw = payload.get("firmwareVersion")

                try:
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(
                            select(ChargePoint).where(ChargePoint.ocpp_id == cp_id)
                        )
                        cp = result.scalar_one_or_none()

                        now_dt = datetime.utcnow()

                        if cp is None:
                            cp = ChargePoint(
                                ocpp_id=cp_id,
                                vendor=vendor,
                                model=model,
                                serial_number=serial,
                                firmware_version=fw,
                                status="available",
                                last_seen_at=now_dt,
                            )
                            session.add(cp)
                            logger.info(f"Új ChargePoint létrehozva DB-ben: {cp_id}")
                        else:
                            cp.vendor = vendor
                            cp.model = model
                            cp.serial_number = serial
                            cp.firmware_version = fw
                            cp.status = "available"
                            cp.last_seen_at = now_dt
                            logger.info(f"ChargePoint frissítve DB-ben: {cp_id}")

                        await session.commit()
                except Exception as e:
                    logger.exception(f"Hiba a ChargePoint mentésekor: {e}")

                now = datetime.utcnow().isoformat() + "Z"
                response = [3, msg_id, {"status": "Accepted", "currentTime": now, "interval": 60}]
                await ws.send_text(json.dumps(response))
                logger.info(f"BootNotification válasz elküldve: {response}")

            elif msg_type == 2 and action == "StatusNotification":
                logger.info("StatusNotification érkezett")
                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))
                logger.info(f"StatusNotification válasz elküldve: {response}")

            elif msg_type == 2 and action == "Heartbeat":
                logger.info("Heartbeat érkezett")
                now = datetime.utcnow().isoformat() + "Z"
                response = [3, msg_id, {"currentTime": now}]
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