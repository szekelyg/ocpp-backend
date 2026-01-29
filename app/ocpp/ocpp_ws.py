import json
import logging
from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select, and_

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, MeterSample, ChargeSession

logger = logging.getLogger("ocpp")


# ---------- time helpers ----------

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now_z() -> str:
    return utcnow().isoformat().replace("+00:00", "Z")


def parse_ocpp_timestamp(ts: Any) -> datetime:
    if not isinstance(ts, str) or not ts.strip():
        return utcnow()

    s = ts.strip()
    try:
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
    cp_id = payload.get("chargeBoxSerialNumber") or payload.get("chargePointSerialNumber")
    if isinstance(cp_id, str) and cp_id.strip():
        return cp_id.strip()
    return None


# ---------- misc helpers ----------

def _as_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip():
            return float(v.strip())
    except Exception:
        return None
    return None


def _as_int(v: Any) -> Optional[int]:
    if isinstance(v, int):
        return v
    f = _as_float(v)
    return int(f) if f is not None else None


def _pick_measurand_sum(sampled_values: Any, measurand: str) -> Optional[float]:
    if not isinstance(sampled_values, list):
        return None

    # 1) phase nélküli összesített
    for sv in sampled_values:
        if isinstance(sv, dict) and sv.get("measurand") == measurand and not sv.get("phase"):
            return _as_float(sv.get("value"))

    # 2) fázisonként összeadjuk
    total = 0.0
    found = False
    for sv in sampled_values:
        if isinstance(sv, dict) and sv.get("measurand") == measurand:
            val = _as_float(sv.get("value"))
            if val is not None:
                total += val
                found = True
    return total if found else None


# ---------- DB helpers ----------

async def upsert_charge_point_from_boot(cp_id: str, payload: dict) -> None:
    vendor = payload.get("chargePointVendor")
    model = payload.get("chargePointModel")
    serial = payload.get("chargePointSerialNumber")
    fw = payload.get("firmwareVersion")

    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))
            cp = res.scalar_one_or_none()

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
            res = await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))
            cp = res.scalar_one_or_none()
            if cp:
                cp.last_seen_at = utcnow()
                await session.commit()
    except Exception as e:
        logger.exception(f"Hiba last_seen_at frissítéskor: {e}")


async def find_active_session_id(session, cp_db_id: int, connector_id: Optional[int]) -> Optional[int]:
    if connector_id is None:
        return None

    res = await session.execute(
        select(ChargeSession)
        .where(
            and_(
                ChargeSession.charge_point_id == cp_db_id,
                ChargeSession.connector_id == connector_id,
                ChargeSession.finished_at.is_(None),
            )
        )
        .order_by(ChargeSession.started_at.desc())
        .limit(1)
    )
    cs = res.scalar_one_or_none()
    return cs.id if cs else None


# ---------- Transaction handlers ----------

async def start_transaction(cp_id: str, payload: dict) -> Optional[int]:
    """
    StartTransaction payload tipikusan: { connectorId, idTag, timestamp, meterStart, ... }
    """
    try:
        connector_id = _as_int(payload.get("connectorId"))
        id_tag = payload.get("idTag")
        ts = parse_ocpp_timestamp(payload.get("timestamp"))

        async with AsyncSessionLocal() as session:
            cp = (await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))).scalar_one_or_none()
            if not cp:
                logger.warning(f"StartTransaction: nincs ilyen charge_point ocpp_id={cp_id}")
                return None

            cs = ChargeSession(
                charge_point_id=cp.id,
                connector_id=connector_id,
                user_tag=id_tag if isinstance(id_tag, str) else None,
                started_at=ts,
                finished_at=None,
                energy_kwh=None,
                cost_huf=None,
                ocpp_transaction_id=None,
            )
            session.add(cs)
            await session.flush()  # cs.id megvan

            # egyszerű, stabil: a transactionId = session db id
            cs.ocpp_transaction_id = str(cs.id)

            cp.last_seen_at = utcnow()
            await session.commit()

            logger.info(f"Session indítva: session_id={cs.id}, tx_id={cs.ocpp_transaction_id}, connector={connector_id}")
            return cs.id
    except Exception as e:
        logger.exception(f"Hiba StartTransaction mentésekor: {e}")
        return None


async def stop_transaction(cp_id: str, payload: dict) -> None:
    """
    StopTransaction payload tipikusan: { transactionId, timestamp, meterStop, reason, ... }
    """
    try:
        transaction_id = payload.get("transactionId")
        ts = parse_ocpp_timestamp(payload.get("timestamp"))
        meter_stop = _as_float(payload.get("meterStop"))  # Wh (ha küldi)

        async with AsyncSessionLocal() as session:
            cp = (await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))).scalar_one_or_none()
            if not cp:
                logger.warning(f"StopTransaction: nincs ilyen charge_point ocpp_id={cp_id}")
                return

            res = await session.execute(
                select(ChargeSession).where(
                    and_(
                        ChargeSession.charge_point_id == cp.id,
                        ChargeSession.ocpp_transaction_id == str(transaction_id),
                    )
                ).limit(1)
            )
            cs = res.scalar_one_or_none()
            if not cs:
                logger.warning(f"StopTransaction: nincs session tx_id={transaction_id} (cp_db_id={cp.id})")
                return

            cs.finished_at = ts

            # első/utolsó sample DB-ből idő szerint (nem relationship sorrend!)
            first_wh = None
            last_wh = None

            first = (await session.execute(
                select(MeterSample)
                .where(MeterSample.session_id == cs.id)
                .order_by(MeterSample.ts.asc())
                .limit(1)
            )).scalar_one_or_none()

            last = (await session.execute(
                select(MeterSample)
                .where(MeterSample.session_id == cs.id)
                .order_by(MeterSample.ts.desc())
                .limit(1)
            )).scalar_one_or_none()

            if first and first.energy_wh_total is not None:
                first_wh = float(first.energy_wh_total)

            if last and last.energy_wh_total is not None:
                last_wh = float(last.energy_wh_total)

            # fallback: meterStop, ha a last nincs
            if last_wh is None and meter_stop is not None:
                last_wh = float(meter_stop)

            if first_wh is not None and last_wh is not None and last_wh >= first_wh:
                cs.energy_kwh = (last_wh - first_wh) / 1000.0

            cp.last_seen_at = utcnow()
            await session.commit()

            logger.info(f"Session lezárva: session_id={cs.id}, tx_id={cs.ocpp_transaction_id}, energy_kwh={cs.energy_kwh}")
    except Exception as e:
        logger.exception(f"Hiba StopTransaction mentésekor: {e}")


# ---------- MeterValues ----------

async def save_meter_values(cp_id: str, payload: dict) -> None:
    """
    payload: { connectorId, meterValue: [ { timestamp, sampledValue:[...]} ] }
    """
    try:
        connector_id = _as_int(payload.get("connectorId"))
        meter_values = payload.get("meterValue")
        if not isinstance(meter_values, list) or not meter_values:
            return

        async with AsyncSessionLocal() as session:
            cp = (await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))).scalar_one_or_none()
            if not cp:
                logger.warning(f"MeterValues: nincs ilyen charge_point ocpp_id={cp_id}")
                return

            active_session_id = await find_active_session_id(session, cp.id, connector_id)

            for mv in meter_values:
                if not isinstance(mv, dict):
                    continue
                ts = parse_ocpp_timestamp(mv.get("timestamp"))
                sampled = mv.get("sampledValue")
                if not isinstance(sampled, list):
                    sampled = []

                sample = MeterSample(
                    charge_point_id=cp.id,
                    session_id=active_session_id,
                    connector_id=connector_id,
                    ts=ts,
                    energy_wh_total=_pick_measurand_sum(sampled, "Energy.Active.Import.Register"),
                    power_w=_pick_measurand_sum(sampled, "Power.Active.Import"),
                    current_a=_pick_measurand_sum(sampled, "Current.Import"),
                    created_at=utcnow(),
                )
                session.add(sample)

            cp.last_seen_at = utcnow()
            await session.commit()

            logger.info(
                f"MeterValues mentve: ocpp_id={cp_id} cp_db_id={cp.id} connector={connector_id} session_id={active_session_id} count={len(meter_values)}"
            )
    except Exception as e:
        logger.exception(f"Hiba MeterValues mentésekor: {e}")


# ---------- main WS handler ----------

async def handle_ocpp(ws: WebSocket, charge_point_id: Optional[str] = None):
    await ws.accept()
    logger.info(f"OCPP kapcsolat nyitva (path_cp_id={charge_point_id})")

    cp_id: Optional[str] = charge_point_id

    try:
        while True:
            raw = await ws.receive_text()
            logger.info(f"OCPP RAW: {raw}")

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Nem JSON, ignorálom")
                continue

            if not isinstance(msg, list) or len(msg) < 3:
                logger.warning("Nem OCPP frame, ignorálom")
                continue

            msg_type = msg[0]
            msg_id = msg[1]
            action = msg[2]
            payload = msg[3] if (len(msg) > 3 and isinstance(msg[3], dict)) else {}

            # csak CALL
            if msg_type != 2:
                logger.info(f"Nem CALL üzenet (type={msg_type}), ignorálom")
                continue

            # Bootból id kinyerés (ha /ocpp route)
            if action == "BootNotification" and cp_id is None:
                cp_id = extract_cp_id_from_boot(payload)
                logger.info(f"Bootból kinyert cp_id={cp_id}")

            # ha még mindig nincs cp_id, nem tudunk DB-hez kötni, de ACK-olunk
            if cp_id is None and action != "BootNotification":
                logger.warning(f"Nincs cp_id, action={action} -> csak ACK")
                await ws.send_text(json.dumps([3, msg_id, {}]))
                continue

            logger.info(f"OCPP CALL: cp_id={cp_id} action={action}")

            if action == "BootNotification":
                if cp_id is None:
                    logger.warning("BootNotification, de nem sikerült cp_id-t kinyerni -> ACK")
                    await ws.send_text(json.dumps([3, msg_id, {"status": "Rejected", "currentTime": iso_utc_now_z(), "interval": 60}]))
                    continue

                await upsert_charge_point_from_boot(cp_id, payload)
                await ws.send_text(json.dumps([3, msg_id, {"status": "Accepted", "currentTime": iso_utc_now_z(), "interval": 60}]))

            elif action == "Heartbeat":
                await touch_last_seen(cp_id)
                await ws.send_text(json.dumps([3, msg_id, {"currentTime": iso_utc_now_z()}]))

            elif action == "StatusNotification":
                await touch_last_seen(cp_id)
                await ws.send_text(json.dumps([3, msg_id, {}]))

            elif action == "FirmwareStatusNotification":
                await touch_last_seen(cp_id)
                await ws.send_text(json.dumps([3, msg_id, {}]))

            elif action == "StartTransaction":
                tx_id = await start_transaction(cp_id, payload)
                await ws.send_text(json.dumps([3, msg_id, {"transactionId": tx_id or 0, "idTagInfo": {"status": "Accepted"}}]))

            elif action == "StopTransaction":
                await stop_transaction(cp_id, payload)
                await ws.send_text(json.dumps([3, msg_id, {"idTagInfo": {"status": "Accepted"}}]))

            elif action == "MeterValues":
                await save_meter_values(cp_id, payload)
                await ws.send_text(json.dumps([3, msg_id, {}]))

            else:
                logger.info(f"Nem kezelt OCPP üzenet: {action} -> ACK")
                await ws.send_text(json.dumps([3, msg_id, {}]))

    except WebSocketDisconnect:
        logger.info("OCPP kapcsolat lezárva (WebSocketDisconnect)")
    except Exception as e:
        logger.exception(f"OCPP hiba: {e}")