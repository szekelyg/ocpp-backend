# app/ocpp/handlers/meter.py
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import and_, select

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, ChargeSession, MeterSample
from app.ocpp.time_utils import parse_ocpp_timestamp, utcnow
from app.ocpp.ocpp_utils import (
    _as_float,
    _as_int,
    _pick_measurand_phases,
    _pick_measurand_sum,
    _price_huf_per_kwh,
)

logger = logging.getLogger("ocpp")


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

            # Csak a TÖLTÉSI TRANZAKCIÓHOZ tartozó kereteket kötjük a sessionhöz:
            #  - van transactionId (a töltő a tranzakcióhoz küldi), VAGY
            #  - connector >= 1 (konkrét csatlakozó, nem állomás-szintű).
            # A connector 0 + tranzakció nélküli "Sample.Clock" keretek állomás-szintű
            # LIFETIME számlálót hordoznak (pl. 161979 Wh) – ezeket NEM szabad a session
            # energiájához/mintáihoz kötni, különben elrontják az elszámolást és a kW-t.
            is_session_frame = (transaction_id is not None) or (connector_id is not None and connector_id >= 1)

            active_session_id = None
            if is_session_frame:
                active_session_id = await _find_session_id_by_tx(session, cp.id, transaction_id)
                if active_session_id is None:
                    active_session_id = await _find_active_session_id(session, cp.id, connector_id)

            now_dt = utcnow()
            last_pw = 0.0
            last_ia = 0.0

            # Előre betöltjük a session objektumot, hogy ne kelljen N+1 lekérés a ciklusban
            cs: Optional[ChargeSession] = None
            if active_session_id is not None:
                cs = (
                    await session.execute(select(ChargeSession).where(ChargeSession.id == int(active_session_id)))
                ).scalar_one_or_none()

            last_valid_energy_total: Optional[float] = None

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

                # Fázisonkénti bontás (ha a töltő küldi) – live megjelenítéshez
                phase_power = _pick_measurand_phases(sampled, "Power.Active.Import")
                phase_current = _pick_measurand_phases(sampled, "Current.Import")
                phases = None
                if phase_power or phase_current:
                    phases = {}
                    if phase_power:
                        phases["power"] = phase_power
                    if phase_current:
                        phases["current"] = phase_current

                energy_total = _pick_measurand_sum(
                    sampled, "Energy.Active.Import.Register", default_measurand=True
                )
                if energy_total is not None:
                    last_valid_energy_total = energy_total

                session.add(
                    MeterSample(
                        charge_point_id=cp.id,
                        session_id=active_session_id,
                        connector_id=connector_id,
                        ts=ts,
                        energy_wh_total=energy_total,
                        power_w=pw,
                        current_a=ia,
                        phases=phases,
                        created_at=now_dt,
                    )
                )

            # live: a ciklus után egyszer frissítjük a session energiát a legutóbbi
            # tranzakció-keret regiszter értékével. A connector-0 lifetime órakeretek
            # ide már nem érnek el (nem session-frame-ek), így nincs szükség a korábbi
            # ">1000 Wh = lifetime, kihagyjuk" heurisztikára – az fagyasztotta be az
            # élő energiát (és számolt ~2x kevesebbet) a session-relatív számlálót
            # küldő töltőknél. Az energia = (regiszter − meterStart), a _recalc végzi.
            if cs is not None and cs.finished_at is None and last_valid_energy_total is not None and cs.meter_start_wh is not None:
                cs.meter_stop_wh = float(last_valid_energy_total)
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