# app/ocpp/handlers/meter.py
from __future__ import annotations

import logging
from typing import Optional, Any

from sqlalchemy import select, and_

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, MeterSample, ChargeSession
from app.ocpp.time_utils import utcnow, parse_ocpp_timestamp
from app.ocpp.parsers import _as_int, _pick_measurand_sum

logger = logging.getLogger("ocpp")


async def _find_active_session_id(session, cp_db_id: int, connector_id: Optional[int]) -> Optional[int]:
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