# app/ocpp/handlers/meter.py
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from sqlalchemy import and_, select

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, ChargeSession, MeterSample
from app.ocpp.time_utils import parse_ocpp_timestamp, utcnow

logger = logging.getLogger("ocpp")


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

    for sv in sampled_values:
        if isinstance(sv, dict) and sv.get("measurand") == measurand and not sv.get("phase"):
            return _as_float(sv.get("value"))

    total = 0.0
    found = False
    for sv in sampled_values:
        if isinstance(sv, dict) and sv.get("measurand") == measurand:
            val = _as_float(sv.get("value"))
            if val is not None:
                total += val
                found = True

    return total if found else None


def _price_huf_per_kwh() -> Optional[float]:
    v = os.environ.get("OCPP_PRICE_HUF_PER_KWH")
    if not v:
        return None
    try:
        x = float(v)
        return x if x >= 0 else None
    except Exception:
        return None


def _recalc_energy_and_cost(cs: ChargeSession) -> None:
    if cs.meter_start_wh is not None and cs.meter_stop_wh is not None:
        try:
            start_wh = float(cs.meter_start_wh)
            stop_wh = float(cs.meter_stop_wh)
            if stop_wh >= start_wh:
                cs.energy_kwh = (stop_wh - start_wh) / 1000.0
        except Exception:
            pass

    price = _price_huf_per_kwh()
    if price is not None and cs.energy_kwh is not None:
        try:
            cs.cost_huf = float(cs.energy_kwh) * float(price)
        except Exception:
            pass


async def _find_active_session_id(session, cp_db_id: int, connector_id: Optional[int]) -> Optional[int]:
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


async def _find_session_id_by_tx(session, cp_db_id: int, transaction_id: Any) -> Optional[int]:
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

            active_session_id = await _find_session_id_by_tx(session, cp.id, transaction_id)
            if active_session_id is None:
                active_session_id = await _find_active_session_id(session, cp.id, connector_id)

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

                energy_total = _pick_measurand_sum(sampled, "Energy.Active.Import.Register")

                session.add(
                    MeterSample(
                        charge_point_id=cp.id,
                        session_id=active_session_id,
                        connector_id=connector_id,
                        ts=ts,
                        energy_wh_total=energy_total,
                        power_w=pw,
                        current_a=ia,
                        created_at=now_dt,
                    )
                )

                # live: ha van session és jön energia total, frissítjük meter_stop_wh + kWh/cost
                if active_session_id is not None and energy_total is not None:
                    cs = (
                        await session.execute(select(ChargeSession).where(ChargeSession.id == int(active_session_id)))
                    ).scalar_one_or_none()
                    if cs and cs.finished_at is None:
                        cs.meter_stop_wh = float(energy_total)
                        _recalc_energy_and_cost(cs)

            cp.last_seen_at = now_dt
            if last_pw > 10 or last_ia > 0.1:
                cp.status = "charging"

            await session.commit()
            logger.info(
                f"MeterValues mentve: cp={cp_id} connector={connector_id} tx={transaction_id} "
                f"session_id={active_session_id} count={len(meter_values)}"
            )

    except Exception as e:
        logger.exception(f"Hiba MeterValues mentésekor: {e}")