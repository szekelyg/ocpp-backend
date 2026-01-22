import json
import logging
from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, MeterSample

logger = logging.getLogger("ocpp")


# ---------- time helpers ----------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now_z() -> str:
    # pl. 2026-01-22T12:10:53.394898Z
    return utcnow().isoformat().replace("+00:00", "Z")


def parse_ocpp_timestamp(ts: Any) -> datetime:
    """
    OCPP timestamp tipikusan: '2026-01-22T12:10:00.000+00:00'
    vagy '...Z'. Ha nincs/rossz, fallback szerveridő.
    """
    if not isinstance(ts, str) or not ts.strip():
        return utcnow()

    s = ts.strip()
    try:
        # datetime.fromisoformat nem szereti a 'Z'-t, ezért csere
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return utcnow()


# ---------- id helper ----------

def extract_cp_id_from_boot(payload: dict) -> Optional[str]:
    # nálad a töltő bootban ezt küldi: chargeBoxSerialNumber = VLTHU001B
    cp_id = payload.get("chargeBoxSerialNumber") or payload.get("chargePointSerialNumber")
    if isinstance(cp_id, str) and cp_id.strip():
        return cp_id.strip()
    return None


# ---------- DB helpers ----------

async def upsert_charge_point_from_boot(cp_id: str, payload: dict) -> None:
    vendor = payload.get("chargePointVendor")
    model = payload.get("chargePointModel")
    serial = payload.get("chargePointSerialNumber")
    fw = payload.get("firmwareVersion")

    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))
            cp = result.scalar_one_or_none()

            now_dt = utcnow()

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


async def touch_last_seen(cp_id: str) -> None:
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))
            cp = result.scalar_one_or_none()
            if cp:
                cp.last_seen_at = utcnow()
                await session.commit()
    except Exception as e:
        logger.exception(f"Hiba last_seen_at frissítéskor: {e}")


def _as_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip() != "":
            return float(v.strip())
    except Exception:
        return None
    return None


def _pick_measurand_sum(sampled_values: list[dict], measurand: str) -> Optional[float]:
    """
    Ha van összesített (phase nélkül), azt veszi.
    Ha csak L1/L2/L3 van, akkor összeadja.
    """
    if not isinstance(sampled_values, list):
        return None

    # 1) keresünk phase nélküli "összes" értéket
    for sv in sampled_values:
        if isinstance(sv, dict) and sv.get("measurand") == measurand and not sv.get("phase"):
            return _as_float(sv.get("value"))

    # 2) ha nincs, fázisonként összeadjuk
    total = 0.0
    found = False
    for sv in sampled_values:
        if isinstance(sv, dict) and sv.get("measurand") == measurand:
            val = _as_float(sv.get("value"))
            if val is not None:
                total += val
                found = True

    return total if found else None


async def save_meter_values(cp_id: str, payload: dict) -> None:
    """
    payload: { connectorId, meterValue: [ { timestamp, sampledValue:[...]} ] }
    """
    try:
        connector_id = payload.get("connectorId")
        if not isinstance(connector_id, int):
            connector_id = _as_float(connector_id)
            connector_id = int(connector_id) if connector_id is not None else None

        meter_values = payload.get("meterValue")
        if not isinstance(meter_values, list) or not meter_values:
            return

        async with AsyncSessionLocal() as session:
            # charge_point DB id
            res = await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))
            cp = res.scalar_one_or_none()
            if not cp:
                return

            now_dt = utcnow()
            cp.last_seen_at = now_dt  # MeterValues is "alive" signal is
            # session_id: egyelőre NULL (majd StartTransaction/StopTransaction alapján kötjük)
            session_id = None

            for mv in meter_values:
                if not isinstance(mv, dict):
                    continue

                ts = parse_ocpp_timestamp(mv.get("timestamp"))
                sampled = mv.get("sampledValue")
                if not isinstance(sampled, list):
                    sampled = []

                energy_wh_total = _pick_measurand_sum(sampled, "Energy.Active.Import.Register")
                power_w = _pick_measurand_sum(sampled, "Power.Active.Import")
                current_a = _pick_measurand_sum(sampled, "Current.Import")

                sample = MeterSample(
                    charge_point_id=cp.id,
                    session_id=session_id,
                    connector_id=connector_id,
                    ts=ts,
                    energy_wh_total=energy_wh_total,
                    power_w=power_w,
                    current_a=current_a,
                    created_at=now_dt,
                )
                session.add(sample)

            await session.commit()

    except Exception as e:
        logger.exception(f"Hiba MeterValues mentésekor: {e}")


# ---------- main WS handler ----------

async def handle_ocpp(ws: WebSocket, charge_point_id: Optional[str] = None):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

    # ha /ocpp/{id}, akkor ez megvan; ha /ocpp, akkor Bootból kinyerjük
    cp_id: Optional[str] = charge_point_id

    try:
        while True:
            raw = await ws.receive_text()
            logger.info(f"OCPP RAW: {raw}")

            # JSON parse
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Nem JSON, ignorálom")
                continue

            # OCPP 1.6 frame:
            # CALL: [2, uniqueId, action, payload]
            if not isinstance(msg, list) or len(msg) < 3:
                logger.warning("Nem OCPP frame, ignorálom")
                continue

            msg_type = msg[0]
            msg_id = msg[1]
            action = msg[2]
            payload = msg[3] if (len(msg) > 3 and isinstance(msg[3], dict)) else {}

            # Mi most csak CALL-t várunk a töltőtől
            if msg_type != 2:
                logger.info(f"Nem CALL üzenet (type={msg_type}), ignorálom")
                continue

            # ha nincs cp_id és Boot jön, próbáljuk kinyerni
            if action == "BootNotification" and cp_id is None:
                cp_id = extract_cp_id_from_boot(payload)
                if cp_id:
                    logger.info(f"ChargePoint ID kinyerve BootNotificationből: {cp_id}")
                else:
                    logger.warning("Nem tudtam ChargePoint ID-t kinyerni BootNotificationből")

            # --- handlers ---
            if action == "BootNotification":
                logger.info("BootNotification érkezett")

                if cp_id:
                    await upsert_charge_point_from_boot(cp_id, payload)

                response = [3, msg_id, {"status": "Accepted", "currentTime": iso_utc_now_z(), "interval": 60}]
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

                response = [3, msg_id, {"currentTime": iso_utc_now_z()}]
                await ws.send_text(json.dumps(response))
                logger.info(f"Heartbeat válasz elküldve: {response}")

            elif action == "FirmwareStatusNotification":
                logger.info("FirmwareStatusNotification érkezett")

                if cp_id:
                    await touch_last_seen(cp_id)

                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))
                logger.info(f"FirmwareStatusNotification válasz elküldve: {response}")

            elif action == "MeterValues":
                logger.info("MeterValues érkezett")

                if cp_id:
                    await save_meter_values(cp_id, payload)

                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))
                logger.info(f"MeterValues válasz elküldve: {response}")

            else:
                logger.info(f"Nem kezelt OCPP üzenet: {action}")
                # azért ACK-oljuk, hogy a töltő ne akadjon (safe default)
                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))

    except WebSocketDisconnect as e:
        logger.info(f"OCPP kapcsolat bezárt: {e}")
    except Exception as e:
        logger.exception(f"Váratlan hiba OCPP kapcsolatban: {e}")