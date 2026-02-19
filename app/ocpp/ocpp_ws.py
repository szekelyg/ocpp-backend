# app/ocpp/ocpp_ws.py
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Any, Dict, Tuple

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, MeterSample, ChargeSession

logger = logging.getLogger("ocpp")

# ======================================================================================
# GLOBAL STATE: aktív WS kapcsolatok + pending CALL-ok (RemoteStart/RemoteStop-hoz)
# ======================================================================================

# cp_id -> websocket
_ACTIVE_WS: Dict[str, WebSocket] = {}

# cp_id -> counter (uniqueId generálás)
_CP_MSG_COUNTER: Dict[str, int] = {}

# (cp_id, unique_id) -> future (CALLRESULT/CALLERROR várás)
_PENDING_CALLS: Dict[Tuple[str, str], asyncio.Future] = {}

# egy lock bőven elég ehhez az MVP-hez
_REGISTRY_LOCK = asyncio.Lock()


# ======================================================================================
# TIME HELPERS
# ======================================================================================

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now_z() -> str:
    return utcnow().isoformat().replace("+00:00", "Z")


def parse_ocpp_timestamp(ts: Any) -> datetime:
    """
    OCPP timestamp lehet "Z" vagy +00:00; mindent UTC datetime-re hozunk.
    """
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


# ======================================================================================
# ID + PARSE HELPERS
# ======================================================================================

def extract_cp_id_from_boot(payload: dict) -> Optional[str]:
    cp_id = payload.get("chargeBoxSerialNumber") or payload.get("chargePointSerialNumber")
    if isinstance(cp_id, str) and cp_id.strip():
        return cp_id.strip()
    return None


async def _next_unique_id(cp_id: str) -> str:
    async with _REGISTRY_LOCK:
        cur = _CP_MSG_COUNTER.get(cp_id, 900_000_000)
        cur += 1
        _CP_MSG_COUNTER[cp_id] = cur
        return str(cur)


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
    """
    sampledValue listából kivesszük a measurand összegzett értékét.
    """
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


def _normalize_cp_status(ocpp_status: Any) -> str:
    if isinstance(ocpp_status, str) and ocpp_status.strip():
        return ocpp_status.strip().lower()
    return "unknown"


# ======================================================================================
# DB HELPERS
# ======================================================================================

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


async def save_status_notification(cp_id: str, payload: dict) -> None:
    """
    StatusNotification payload tipikusan:
    { connectorId, status, errorCode, timestamp }
    """
    try:
        incoming = _normalize_cp_status(payload.get("status"))

        async with AsyncSessionLocal() as session:
            cp = (
                await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))
            ).scalar_one_or_none()
            if not cp:
                return

            cp.last_seen_at = utcnow()

            # Ha van aktív session, ne engedjük, hogy "available" felülírja a chargingot
            active = (
                await session.execute(
                    select(ChargeSession.id).where(
                        and_(
                            ChargeSession.charge_point_id == cp.id,
                            ChargeSession.finished_at.is_(None),
                        )
                    ).limit(1)
                )
            ).first()

            if active and incoming == "available":
                await session.commit()
                return

            cp.status = incoming
            await session.commit()

    except Exception as e:
        logger.exception(f"Hiba StatusNotification mentésekor: {e}")


async def find_active_session_id(session, cp_db_id: int, connector_id: Optional[int]) -> Optional[int]:
    """
    VOLTIE-kompatibilis session keresés:
    - exact connector match
    - ha connectorId=0 -> próbáljuk 1-gyel
    - fallback: bármely aktív session CP-n
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

    sid = await _find_for_connector(connector_id)
    if sid:
        return sid

    if connector_id == 0:
        sid = await _find_for_connector(1)
        if sid:
            return sid

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


async def find_session_id_by_tx(session, cp_db_id: int, transaction_id: Any) -> Optional[int]:
    if transaction_id is None:
        return None
    tx = str(transaction_id)
    res = await session.execute(
        select(ChargeSession.id)
        .where(
            and_(
                ChargeSession.charge_point_id == cp_db_id,
                ChargeSession.ocpp_transaction_id == tx,
                ChargeSession.finished_at.is_(None),
            )
        )
        .limit(1)
    )
    row = res.first()
    return int(row[0]) if row else None


# ======================================================================================
# TRANSACTION HANDLERS
# ======================================================================================

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

            # nálunk CSMS transactionId = session id
            cs.ocpp_transaction_id = str(cs.id)

            # státusz: töltés indul
            cp.status = "charging"
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

            if transaction_id is None:
                logger.warning(f"StopTransaction: nincs transactionId cp={cp_id}")
                return

            res = await session.execute(
                select(ChargeSession)
                .options(selectinload(ChargeSession.samples))
                .where(
                    and_(
                        ChargeSession.charge_point_id == cp.id,
                        ChargeSession.ocpp_transaction_id == str(transaction_id),
                        ChargeSession.finished_at.is_(None),
                    )
                )
                .limit(1)
            )
            cs = res.scalar_one_or_none()
            if not cs:
                logger.warning(f"StopTransaction: nincs nyitott session tx={transaction_id} cp={cp_id}")
                return

            cs.finished_at = ts

            first_wh = None
            last_wh = None

            samples = sorted([s for s in (cs.samples or []) if s.energy_wh_total is not None], key=lambda x: x.ts)
            if samples:
                first_wh = float(samples[0].energy_wh_total)
                last_wh = float(samples[-1].energy_wh_total)

            if (last_wh is None) and (meter_stop is not None):
                last_wh = float(meter_stop)

            if first_wh is not None and last_wh is not None and last_wh >= first_wh:
                cs.energy_kwh = (last_wh - first_wh) / 1000.0

            cp.status = "available"
            cp.last_seen_at = utcnow()

            await session.commit()
            logger.info(f"Session lezárva: id={cs.id} tx={transaction_id} energy_kwh={cs.energy_kwh}")

    except Exception as e:
        logger.exception(f"Hiba StopTransaction mentésekor: {e}")


# ======================================================================================
# METERVALUES HANDLER
# ======================================================================================

async def save_meter_values(cp_id: str, payload: dict) -> None:
    try:
        connector_id = _as_int(payload.get("connectorId"))
        transaction_id = payload.get("transactionId")
        meter_values = payload.get("meterValue")

        if not isinstance(meter_values, list) or not meter_values:
            return

        async with AsyncSessionLocal() as session:
            cp = (await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))).scalar_one_or_none()
            if not cp:
                logger.warning(f"MeterValues: nincs ilyen CP: {cp_id}")
                return

            active_session_id = await find_session_id_by_tx(session, cp.id, transaction_id)
            if active_session_id is None:
                active_session_id = await find_active_session_id(session, cp.id, connector_id)

            now_dt = utcnow()

            last_pw = 0.0
            last_ia = 0.0

            for mv in meter_values:
                if not isinstance(mv, dict):
                    continue

                ts = parse_ocpp_timestamp(mv.get("timestamp"))
                sampled = mv.get("sampledValue")
                if not isinstance(sampled, list):
                    sampled = []

                pw = _pick_measurand_sum(sampled, "Power.Active.Import") or 0.0
                ia = _pick_measurand_sum(sampled, "Current.Import") or 0.0

                last_pw = pw
                last_ia = ia

                sample = MeterSample(
                    charge_point_id=cp.id,
                    session_id=active_session_id,
                    connector_id=connector_id,
                    ts=ts,
                    energy_wh_total=_pick_measurand_sum(sampled, "Energy.Active.Import.Register"),
                    power_w=pw,
                    current_a=ia,
                    created_at=now_dt,
                )
                session.add(sample)

            cp.last_seen_at = now_dt

            # státusz frissítés még commit előtt
            if last_pw > 10 or last_ia > 0.1:
                cp.status = "charging"

            await session.commit()

            logger.info(
                f"MeterValues mentve: cp={cp_id} connector={connector_id} tx={transaction_id} session_id={active_session_id} count={len(meter_values)}"
            )

    except Exception as e:
        logger.exception(f"Hiba MeterValues mentésekor: {e}")


# ======================================================================================
# REMOTE START/STOP (CSMS -> CP)
# ======================================================================================

async def _send_call_and_wait(cp_id: str, action: str, payload: dict, timeout_s: float = 12.0) -> dict:
    """
    OCPP CALL (2) küldése a töltőnek és CALLRESULT (3) / CALLERROR (4) megvárása.
    """
    async with _REGISTRY_LOCK:
        ws = _ACTIVE_WS.get(cp_id)
        if ws is None:
            raise RuntimeError(f"Nincs aktív WS kapcsolat ehhez a töltőhöz: {cp_id}")

    uid = await _next_unique_id(cp_id)
    frame = [2, uid, action, payload]

    fut = asyncio.get_running_loop().create_future()
    async with _REGISTRY_LOCK:
        _PENDING_CALLS[(cp_id, uid)] = fut

    try:
        await ws.send_text(json.dumps(frame))
        logger.info(f"CSMS->CP CALL elküldve: cp={cp_id} action={action} uid={uid}")

        res = await asyncio.wait_for(fut, timeout=timeout_s)
        return res if isinstance(res, dict) else {}

    finally:
        async with _REGISTRY_LOCK:
            _PENDING_CALLS.pop((cp_id, uid), None)


async def remote_start_transaction(cp_id: str, connector_id: int = 1, id_tag: str = "ANON") -> dict:
    """
    RemoteStartTransaction (OCPP 1.6): { connectorId?, idTag, chargingProfile? }
    """
    payload = {"connectorId": int(connector_id), "idTag": str(id_tag)}
    return await _send_call_and_wait(cp_id, "RemoteStartTransaction", payload, timeout_s=12.0)


async def remote_stop_transaction(cp_id: str, transaction_id: Any) -> dict:
    """
    RemoteStopTransaction (OCPP 1.6): { transactionId }
    """
    if transaction_id is None:
        return {"status": "Rejected", "reason": "missing_transaction_id"}
    try:
        tx = int(transaction_id)
    except Exception:
        tx = transaction_id
    payload = {"transactionId": tx}
    return await _send_call_and_wait(cp_id, "RemoteStopTransaction", payload, timeout_s=12.0)


# ======================================================================================
# MAIN WS HANDLER
# ======================================================================================

async def handle_ocpp(ws: WebSocket, charge_point_id: Optional[str] = None):
    await ws.accept()
    logger.info("OCPP kapcsolat nyitva")

    cp_id: Optional[str] = charge_point_id

    # ha path-ban jött az ID, regisztráljuk rögtön
    if cp_id:
        async with _REGISTRY_LOCK:
            _ACTIVE_WS[cp_id] = ws

    try:
        while True:
            raw = await ws.receive_text()
            logger.info(f"OCPP RAW: {raw}")

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Nem JSON, ignorálom")
                continue

            if not isinstance(msg, list) or len(msg) < 2:
                logger.warning("Nem OCPP frame, ignorálom")
                continue

            msg_type = msg[0]
            unique_id = str(msg[1])

            # --------------------------------------------------------------------------
            # CALLRESULT (3) / CALLERROR (4) - pending remote CALL-ok miatt
            # --------------------------------------------------------------------------
            if msg_type in (3, 4):
                if not cp_id:
                    continue

                key = (cp_id, unique_id)

                async with _REGISTRY_LOCK:
                    fut = _PENDING_CALLS.get(key)

                if fut and not fut.done():
                    if msg_type == 3:
                        payload = msg[2] if (len(msg) > 2 and isinstance(msg[2], dict)) else {}
                        fut.set_result(payload)
                    else:
                        # [4, uniqueId, errorCode, errorDescription, errorDetails]
                        err = {
                            "status": "Error",
                            "errorCode": msg[2] if len(msg) > 2 else "Unknown",
                            "errorDescription": msg[3] if len(msg) > 3 else "",
                            "errorDetails": msg[4] if len(msg) > 4 else {},
                        }
                        fut.set_result(err)

                continue

            # --------------------------------------------------------------------------
            # csak CALL (2)
            # --------------------------------------------------------------------------
            if msg_type != 2 or len(msg) < 3:
                logger.info(f"Nem CALL üzenet (type={msg_type}), ignorálom")
                continue

            action = msg[2]
            payload = msg[3] if (len(msg) > 3 and isinstance(msg[3], dict)) else {}

            # Bootból id kinyerés (ha /ocpp route)
            if action == "BootNotification" and cp_id is None:
                cp_id = extract_cp_id_from_boot(payload)
                if cp_id:
                    logger.info(f"ChargePoint ID kinyerve BootNotificationből: {cp_id}")
                    async with _REGISTRY_LOCK:
                        _ACTIVE_WS[cp_id] = ws
                else:
                    logger.warning("Nem tudtam ChargePoint ID-t kinyerni BootNotificationből")

            if not cp_id:
                # nincs cp_id, de ACK-oljunk safe defaulttal
                await ws.send_text(json.dumps([3, unique_id, {}]))
                continue

            # biztonság kedvéért: ha cp_id már megvan, tartsuk a registry-t frissen
            async with _REGISTRY_LOCK:
                if _ACTIVE_WS.get(cp_id) is not ws:
                    _ACTIVE_WS[cp_id] = ws

            # --------------------------------------------------------------------------
            # ACTION HANDLERS
            # --------------------------------------------------------------------------
            if action == "BootNotification":
                await upsert_charge_point_from_boot(cp_id, payload)
                response = [3, unique_id, {"status": "Accepted", "currentTime": iso_utc_now_z(), "interval": 60}]
                await ws.send_text(json.dumps(response))

            elif action == "Heartbeat":
                await touch_last_seen(cp_id)
                response = [3, unique_id, {"currentTime": iso_utc_now_z()}]
                await ws.send_text(json.dumps(response))

            elif action == "StatusNotification":
                await save_status_notification(cp_id, payload)
                response = [3, unique_id, {}]
                await ws.send_text(json.dumps(response))

            elif action == "FirmwareStatusNotification":
                await touch_last_seen(cp_id)
                response = [3, unique_id, {}]
                await ws.send_text(json.dumps(response))

            elif action == "StartTransaction":
                tx_id = await start_transaction(cp_id, payload)
                response = [3, unique_id, {"transactionId": int(tx_id or 0), "idTagInfo": {"status": "Accepted"}}]
                await ws.send_text(json.dumps(response))

            elif action == "StopTransaction":
                await stop_transaction(cp_id, payload)
                response = [3, unique_id, {"idTagInfo": {"status": "Accepted"}}]
                await ws.send_text(json.dumps(response))

            elif action == "MeterValues":
                await save_meter_values(cp_id, payload)
                response = [3, unique_id, {}]
                await ws.send_text(json.dumps(response))

            else:
                logger.info(f"Nem kezelt OCPP üzenet: {action} (ACK safe default)")
                response = [3, unique_id, {}]
                await ws.send_text(json.dumps(response))

    except WebSocketDisconnect:
        logger.info("OCPP kapcsolat lezárva (WebSocketDisconnect)")
    except Exception as e:
        logger.exception(f"OCPP hiba: {e}")
    finally:
        # cleanup registry
        if cp_id:
            async with _REGISTRY_LOCK:
                if _ACTIVE_WS.get(cp_id) is ws:
                    _ACTIVE_WS.pop(cp_id, None)
        logger.info(f"OCPP cleanup kész (cp_id={cp_id})")