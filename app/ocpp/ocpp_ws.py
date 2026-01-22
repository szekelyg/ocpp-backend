import logging
import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint

logger = logging.getLogger("ocpp")


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utcnow():
    return datetime.now(timezone.utc)


def extract_cp_id_from_payload(payload: dict) -> Optional[str]:
    cp_id = payload.get("chargeBoxSerialNumber") or payload.get("chargePointSerialNumber")
    if isinstance(cp_id, str) and cp_id.strip():
        return cp_id.strip()
    return None


async def upsert_charge_point_from_boot(charge_point_id: str, payload: dict) -> None:
    vendor = payload.get("chargePointVendor")
    model = payload.get("chargePointModel")
    serial = payload.get("chargePointSerialNumber")
    fw = payload.get("firmwareVersion")

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ChargePoint).where(ChargePoint.ocpp_id == charge_point_id)
            )
            cp = result.scalar_one_or_none()

            now_dt = utcnow()

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


async def touch_last_seen(charge_point_id: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ChargePoint).where(ChargePoint.ocpp_id == charge_point_id)
            )
            cp = result.scalar_one_or_none()
            if cp:
                cp.last_seen_at = utcnow()
                await session.commit()
    except Exception as e:
        logger.exception(f"Hiba last_seen_at frissítéskor: {e}")


async def handle_ocpp(ws: WebSocket, charge_point_id: Optional[str] = None):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

    cp_id: Optional[str] = charge_point_id

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

            # csak CALL (töltő -> szerver) érdekel itt
            if msg_type != 2:
                logger.info(f"Nem CALL üzenet (type={msg_type}), ignorálom")
                continue

            # ha /ocpp (id nélkül), akkor BootNotificationből szedjük ki
            if action == "BootNotification" and cp_id is None:
                cp_id = extract_cp_id_from_payload(payload)
                if cp_id:
                    logger.info(f"ChargePoint ID kinyerve BootNotificationből: {cp_id}")
                else:
                    logger.warning("Nem tudtam ChargePoint ID-t kinyerni BootNotificationből")

            if action == "BootNotification":
                logger.info("BootNotification érkezett")

                if cp_id:
                    await upsert_charge_point_from_boot(cp_id, payload)

                response = [3, msg_id, {"status": "Accepted", "currentTime": iso_utc_now(), "interval": 60}]
                await ws.send_text(json.dumps(response))
                logger.info(f"BootNotification válasz elküldve: {response}")

            elif action == "StatusNotification":
                logger.info("StatusNotification érkezett")

                if cp_id:
                    await touch_last_seen(cp_id)

                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))
                logger.info(f"StatusNotification válasz elküldve: {response}")

            elif action == "Heartbeat":
                logger.info("Heartbeat érkezett")

                if cp_id:
                    await touch_last_seen(cp_id)

                response = [3, msg_id, {"currentTime": iso_utc_now()}]
                await ws.send_text(json.dumps(response))
                logger.info(f"Heartbeat válasz elküldve: {response}")

            elif action == "MeterValues":
                logger.info("MeterValues érkezett")

                if cp_id:
                    await touch_last_seen(cp_id)

                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))
                logger.info(f"MeterValues válasz elküldve: {response}")

            elif action == "FirmwareStatusNotification":
                logger.info("FirmwareStatusNotification érkezett")

                if cp_id:
                    await touch_last_seen(cp_id)

                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))
                logger.info(f"FirmwareStatusNotification válasz elküldve: {response}")

            else:
                logger.info(f"Nem kezelt OCPP üzenet: {action}")

    except WebSocketDisconnect as e:
        logger.info(f"OCPP kapcsolat bezárt: {e}")
    except Exception as e:
        logger.exception(f"Váratlan hiba OCPP kapcsolatban: {e}")