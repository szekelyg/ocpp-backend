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


async def touch_last_seen(cp_id: str) -> None:
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))
        cp = res.scalar_one_or_none()
        if cp:
            cp.last_seen_at = utcnow()
            await session.commit()


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
    connector_id = _as_int(payload.get("connectorId"))
    id_tag = payload.get("idTag")
    ts = parse_ocpp_timestamp(payload.get("timestamp"))

    async with AsyncSessionLocal() as session:
        cp = (await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))).scalar_one_or_none()
        if not cp:
            return None

        cs = ChargeSession(
            charge_point_id=cp.id,
            connector_id=connector_id,
            user_tag=id_tag,
            started_at=ts,
        )

        session.add(cs)
        await session.flush()

        cs.ocpp_transaction_id = str(cs.id)

        cp.last_seen_at = utcnow()
        await session.commit()

        logger.info(f"Session indítva: {cs.id}")
        return cs.id


async def stop_transaction(cp_id: str, payload: dict) -> None:
    transaction_id = payload.get("transactionId")
    ts = parse_ocpp_timestamp(payload.get("timestamp"))

    async with AsyncSessionLocal() as session:
        cp = (await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))).scalar_one_or_none()
        if not cp:
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
        )

        cs = res.scalar_one_or_none()
        if not cs:
            return

        cs.finished_at = ts

        # energia számítás: első és utolsó sample
        samples = cs.samples
        if len(samples) >= 2:
            first = samples[0].energy_wh_total
            last = samples[-1].energy_wh_total

            if first and last and last >= first:
                cs.energy_kwh = (last - first) / 1000.0

        await session.commit()
        logger.info(f"Session lezárva: {cs.id}")


# ---------- MeterValues ----------

async def save_meter_values(cp_id: str, payload: dict) -> None:
    connector_id = _as_int(payload.get("connectorId"))
    meter_values = payload.get("meterValue")

    if not isinstance(meter_values, list):
        return

    async with AsyncSessionLocal() as session:
        cp = (await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))).scalar_one_or_none()
        if not cp:
            return

        active_session_id = await find_active_session_id(session, cp.id, connector_id)

        for mv in meter_values:
            ts = parse_ocpp_timestamp(mv.get("timestamp"))
            sampled = mv.get("sampledValue", [])

            sample = MeterSample(
                charge_point_id=cp.id,
                session_id=active_session_id,
                connector_id=connector_id,
                ts=ts,
                energy_wh_total=_pick_measurand_sum(sampled, "Energy.Active.Import.Register"),
                power_w=_pick_measurand_sum(sampled, "Power.Active.Import"),
                current_a=_pick_measurand_sum(sampled, "Current.Import"),
            )
            session.add(sample)

        cp.last_seen_at = utcnow()
        await session.commit()


# ---------- main WS handler ----------

async def handle_ocpp(ws: WebSocket, charge_point_id: Optional[str] = None):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

    cp_id = charge_point_id

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            msg_type, msg_id, action = msg[0], msg[1], msg[2]
            payload = msg[3] if len(msg) > 3 else {}

            if msg_type != 2:
                continue

            if action == "BootNotification" and cp_id is None:
                cp_id = extract_cp_id_from_boot(payload)

            if action == "BootNotification":
                await upsert_charge_point_from_boot(cp_id, payload)
                await ws.send_text(json.dumps([3, msg_id, {
                    "status": "Accepted",
                    "currentTime": iso_utc_now_z(),
                    "interval": 60
                }]))

            elif action == "Heartbeat":
                await touch_last_seen(cp_id)
                await ws.send_text(json.dumps([3, msg_id, {"currentTime": iso_utc_now_z()}]))

            elif action == "StartTransaction":
                tx_id = await start_transaction(cp_id, payload)
                await ws.send_text(json.dumps([3, msg_id, {
                    "transactionId": tx_id,
                    "idTagInfo": {"status": "Accepted"}
                }]))

            elif action == "StopTransaction":
                await stop_transaction(cp_id, payload)
                await ws.send_text(json.dumps([3, msg_id, {}]))

            elif action == "MeterValues":
                await save_meter_values(cp_id, payload)
                await ws.send_text(json.dumps([3, msg_id, {}]))

            else:
                await ws.send_text(json.dumps([3, msg_id, {}]))

    except WebSocketDisconnect:
        logger.info("OCPP kapcsolat lezárva")
    except Exception as e:
        logger.exception(f"OCPP hiba: {e}")