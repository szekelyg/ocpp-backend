import json
import logging
from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

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

    # 1) összesített (phase nélkül)
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
                logger.info(f"Új ChargePoint létrehozva: {cp_id}")
            else:
                cp.vendor = vendor
                cp.model = model
                cp.serial_number = serial
                cp.firmware_version = fw
                cp.status = "available"
                cp.last_seen_at = now_dt
                logger.info(f"ChargePoint frissítve: {cp_id}")

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
    """
    VOLTIE-kompatibilis:
    - először exact match connector_id-ra
    - ha MeterValues connectorId=0, akkor próbáljuk meg connector=1-gyel is (VOLTIE tipikusan így viselkedik)
    - ha még mindig nincs, fallback: bármely aktív session ezen a CP-n
    """
    async def _find_for_connector(cid: Optional[int]) -> Optional[int]:
        if cid is None:
            return None
        res = await session.execute(
            select(ChargeSession.id)
            .where(
                and_(
                    ChargeSession.charge_point_id == cp_db_id,
                    ChargeSession.connector_id == cid,
                    ChargeSession.finished_at.is_(None),
                )
            )
            .order_by(ChargeSession.started_at.desc())
            .limit(1)
        )
        row = res.first()
        return int(row[0]) if row else None

    # 1) exact
    sid = await _find_for_connector(connector_id)
    if sid:
        return sid

    # 2) VOLTIE workaround: MeterValues connectorId=0 -> session connector=1
    if connector_id == 0:
        sid = await _find_for_connector(1)
        if sid:
            return sid

    # 3) fallback: bármely aktív session ugyanazon CP-n
    res = await session.execute(
        select(ChargeSession.id)
        .where(
            and_(
                ChargeSession.charge_point_id == cp_db_id,
                ChargeSession.finished_at.is_(None),
            )
        )
        .order_by(ChargeSession.started_at.desc())
        .limit(1)
    )
    row = res.first()
    return int(row[0]) if row else None


# ---------- Transaction handlers ----------

async def start_transaction(cp_id: str, payload: dict) -> Optional[int]:
    """
    StartTransaction payload tipikusan:
    { connectorId, idTag, timestamp, meterStart, ... }
    """
    try:
        connector_id = _as_int(payload.get("connectorId"))
        id_tag = payload.get("idTag")
        ts = parse_ocpp_timestamp(payload.get("timestamp"))

        async with AsyncSessionLocal() as session:
            cp = (await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))).scalar_one_or_none()
            if not cp:
                logger.warning(f"StartTransaction: nincs ilyen CP: {cp_id}")
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
            await session.flush()  # cs.id

            cs.ocpp_transaction_id = str(cs.id)
            cp.last_seen_at = utcnow()

            await session.commit()
            logger.info(f"Session indítva: id={cs.id} cp={cp_id} connector={connector_id}")
            return cs.id

    except Exception as e:
        logger.exception(f"Hiba StartTransaction mentésekor: {e}")
        return None


async def stop_transaction(cp_id: str, payload: dict) -> None:
    """
    StopTransaction payload tipikusan:
    { transactionId, timestamp, meterStop, reason, idTag, ... }
    """
    try:
        transaction_id = payload.get("transactionId")
        ts = parse_ocpp_timestamp(payload.get("timestamp"))
        meter_stop = _as_float(payload.get("meterStop"))  # Wh

        async with AsyncSessionLocal() as session:
            cp = (await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))).scalar_one_or_none()
            if not cp:
                logger.warning(f"StopTransaction: nincs ilyen CP: {cp_id}")
                return

            res = await session.execute(
                select(ChargeSession)
                .options(selectinload(ChargeSession.samples))
                .where(
                    and_(
                        ChargeSession.charge_point_id == cp.id,
                        ChargeSession.ocpp_transaction_id == str(transaction_id),
                    )
                )
                .limit(1)
            )
            cs = res.scalar_one_or_none()
            if not cs:
                logger.warning(f"StopTransaction: nincs ilyen session tx={transaction_id} cp={cp_id}")
                return

            cs.finished_at = ts

            # energia számítás (robosztus):
            # 1) ha vannak session-hez kötött minták: első/utolsó energy_wh_total
            # 2) ha nincs: próbáljuk meterStop - (session első mintája nélküli) -> nem tudunk különbséget, marad None
            # Megjegyzés: ha a szimulátor küld meterStart-ot is, akkor érdemes majd eltárolni cs-ben (külön oszlop).
            first_wh = None
            last_wh = None

            # a session-hez kötött minták biztos sorrendben:
            samples = sorted([s for s in (cs.samples or []) if s.energy_wh_total is not None], key=lambda x: x.ts)
            if samples:
                first_wh = float(samples[0].energy_wh_total)
                last_wh = float(samples[-1].energy_wh_total)

            if (last_wh is None) and (meter_stop is not None):
                last_wh = float(meter_stop)

            if first_wh is not None and last_wh is not None and last_wh >= first_wh:
                cs.energy_kwh = (last_wh - first_wh) / 1000.0

            cp.last_seen_at = utcnow()
            await session.commit()
            logger.info(f"Session lezárva: id={cs.id} tx={transaction_id} energy_kwh={cs.energy_kwh}")

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
                logger.warning(f"MeterValues: nincs ilyen CP: {cp_id}")
                return

            active_session_id = await find_active_session_id(session, cp.id, connector_id)

            now_dt = utcnow()
            for mv in meter_values:
                if not isinstance(mv, dict):
                    continue

                ts = parse_ocpp_timestamp(mv.get("timestamp"))
                sampled = mv.get("sampledValue")
                if not isinstance(sampled, list):
                    sampled = []

                sample = MeterSample(
                    charge_point_id=cp.id,
                    session_id=active_session_id,  # <-- EZ A LÉNYEG
                    connector_id=connector_id,
                    ts=ts,
                    energy_wh_total=_pick_measurand_sum(sampled, "Energy.Active.Import.Register"),
                    power_w=_pick_measurand_sum(sampled, "Power.Active.Import"),
                    current_a=_pick_measurand_sum(sampled, "Current.Import"),
                    created_at=now_dt,
                )
                session.add(sample)

            cp.last_seen_at = now_dt
            await session.commit()

            logger.info(
                f"MeterValues mentve: cp={cp_id} connector={connector_id} session_id={active_session_id} count={len(meter_values)}"
            )

    except Exception as e:
        logger.exception(f"Hiba MeterValues mentésekor: {e}")


# ---------- main WS handler ----------

async def handle_ocpp(ws: WebSocket, charge_point_id: Optional[str] = None):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

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

            # csak CALL (2)
            if msg_type != 2:
                logger.info(f"Nem CALL üzenet (type={msg_type}), ignorálom")
                continue

            # Bootból id kinyerés (ha /ocpp route)
            if action == "BootNotification" and cp_id is None:
                cp_id = extract_cp_id_from_boot(payload)
                if cp_id:
                    logger.info(f"ChargePoint ID kinyerve BootNotificationből: {cp_id}")
                else:
                    logger.warning("Nem tudtam ChargePoint ID-t kinyerni BootNotificationből")

            if not cp_id:
                # ha nincs CP azonosító, akkor sem állunk meg, csak ACK safe default
                await ws.send_text(json.dumps([3, msg_id, {}]))
                continue

            if action == "BootNotification":
                logger.info("BootNotification érkezett")
                await upsert_charge_point_from_boot(cp_id, payload)
                response = [3, msg_id, {"status": "Accepted", "currentTime": iso_utc_now_z(), "interval": 60}]
                await ws.send_text(json.dumps(response))
                logger.info(f"BootNotification válasz elküldve: {response}")

            elif action == "Heartbeat":
                logger.info("Heartbeat érkezett")
                await touch_last_seen(cp_id)
                response = [3, msg_id, {"currentTime": iso_utc_now_z()}]
                await ws.send_text(json.dumps(response))

            elif action == "StatusNotification":
                logger.info("StatusNotification érkezett")
                await touch_last_seen(cp_id)
                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))

            elif action == "FirmwareStatusNotification":
                logger.info("FirmwareStatusNotification érkezett")
                await touch_last_seen(cp_id)
                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))

            elif action == "StartTransaction":
                logger.info("StartTransaction érkezett")
                tx_id = await start_transaction(cp_id, payload)
                response = [3, msg_id, {"transactionId": int(tx_id or 0), "idTagInfo": {"status": "Accepted"}}]
                await ws.send_text(json.dumps(response))
                logger.info(f"StartTransaction válasz elküldve: {response}")

            elif action == "StopTransaction":
                logger.info("StopTransaction érkezett")
                await stop_transaction(cp_id, payload)
                response = [3, msg_id, {"idTagInfo": {"status": "Accepted"}}]
                await ws.send_text(json.dumps(response))

            elif action == "MeterValues":
                logger.info("MeterValues érkezett")
                await save_meter_values(cp_id, payload)
                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))

            else:
                logger.info(f"Nem kezelt OCPP üzenet: {action} (ACK safe default)")
                response = [3, msg_id, {}]
                await ws.send_text(json.dumps(response))

    except WebSocketDisconnect:
        logger.info("OCPP kapcsolat lezárva")
    except Exception as e:
        logger.exception(f"OCPP hiba: {e}")