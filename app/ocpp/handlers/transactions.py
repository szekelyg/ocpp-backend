# app/ocpp/handlers/transactions.py
from __future__ import annotations

import os
import logging
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, ChargeSession
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
    # preferált: meterStart/meterStop
    if cs.meter_start_wh is not None and cs.meter_stop_wh is not None:
        try:
            start_wh = float(cs.meter_start_wh)
            stop_wh = float(cs.meter_stop_wh)
            if stop_wh >= start_wh:
                cs.energy_kwh = (stop_wh - start_wh) / 1000.0
        except Exception:
            pass

    # ár opcionális
    price = _price_huf_per_kwh()
    if price is not None and cs.energy_kwh is not None:
        try:
            cs.cost_huf = float(cs.energy_kwh) * float(price)
        except Exception:
            pass


async def start_transaction(cp_id: str, payload: dict) -> Optional[int]:
    """
    StartTransaction payload tipikusan:
    { connectorId, idTag, timestamp, meterStart, ... }
    """
    try:
        connector_id = _as_int(payload.get("connectorId"))
        id_tag = payload.get("idTag")
        ts = parse_ocpp_timestamp(payload.get("timestamp"))
        meter_start = _as_float(payload.get("meterStart"))  # Wh

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
                meter_start_wh=meter_start,
                meter_stop_wh=None,
                energy_kwh=None,
                cost_huf=None,
                ocpp_transaction_id=None,
            )
            session.add(cs)
            await session.flush()

            # nálunk CSMS transactionId = session id
            cs.ocpp_transaction_id = str(cs.id)

            cp.status = "charging"
            cp.last_seen_at = utcnow()

            await session.commit()
            logger.info(
                f"Session indítva: id={cs.id} cp={cp_id} connector={connector_id} meter_start_wh={meter_start}"
            )
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
            cs.meter_stop_wh = meter_stop

            # 1) preferált: meterStart/meterStop
            _recalc_energy_and_cost(cs)

            # 2) fallback: sample-alapú, ha nincs meterStart
            if cs.energy_kwh is None:
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

                _recalc_energy_and_cost(cs)

            cp.status = "available"
            cp.last_seen_at = utcnow()

            await session.commit()
            logger.info(
                f"Session lezárva: id={cs.id} tx={transaction_id} meter_stop_wh={meter_stop} "
                f"energy_kwh={cs.energy_kwh} cost_huf={cs.cost_huf}"
            )

    except Exception as e:
        logger.exception(f"Hiba StopTransaction mentésekor: {e}")