# app/ocpp/handlers/transactions.py
from __future__ import annotations

import logging
from typing import Optional, Any

from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, ChargeSession
from app.ocpp.time_utils import utcnow
from app.ocpp.parsers import _as_int, _as_float
from app.ocpp.time_utils import parse_ocpp_timestamp

logger = logging.getLogger("ocpp")


async def _find_open_session(session, cp_db_id: int, connector_id: Optional[int]) -> Optional[ChargeSession]:
    q = (
        select(ChargeSession)
        .where(
            and_(
                ChargeSession.charge_point_id == cp_db_id,
                ChargeSession.finished_at.is_(None),
            )
        )
        .order_by(ChargeSession.started_at.desc())
        .limit(5)
    )
    res = await session.execute(q)
    candidates = res.scalars().all()

    if connector_id is not None:
        for cs in candidates:
            if cs.connector_id == connector_id:
                return cs

        # VOLTIE-szerű fallback: ha 0 jön, próbáljuk 1-et
        if connector_id == 0:
            for cs in candidates:
                if cs.connector_id == 1:
                    return cs

    return candidates[0] if candidates else None


async def start_transaction(cp_id: str, payload: dict) -> Optional[int]:
    """
    StartTransaction payload tipikusan:
    { connectorId, idTag, timestamp, meterStart, ... }

    FONTOS: Ha a webes API már létrehozott egy "nyitott" sessiont (pending),
    akkor itt NE hozzunk létre újat, hanem azt használjuk.
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

            # 1) próbáljuk a meglévő nyitott sessiont használni
            existing = await _find_open_session(session, cp.id, connector_id)

            if existing:
                # csak óvatos frissítések
                if existing.connector_id is None and connector_id is not None:
                    existing.connector_id = connector_id
                if existing.user_tag is None and isinstance(id_tag, str) and id_tag:
                    existing.user_tag = id_tag

                # started_at nálad kötelező (nullable=False), de ha API csinálta, már lesz.
                # Itt nem írjuk felül, kivéve ha valamiért None lenne.
                if getattr(existing, "started_at", None) is None:
                    existing.started_at = ts  # védőháló

                # ha nincs ocpp_transaction_id, nálunk az session id stringje
                if not existing.ocpp_transaction_id:
                    existing.ocpp_transaction_id = str(existing.id)

                cp.status = "charging"
                cp.last_seen_at = utcnow()

                await session.commit()
                logger.info(f"Session reuse StartTransaction: id={existing.id} cp={cp_id} connector={connector_id}")
                return int(existing.id)

            # 2) nincs nyitott -> létrehozunk (régi viselkedés)
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
            await session.flush()

            cs.ocpp_transaction_id = str(cs.id)

            cp.status = "charging"
            cp.last_seen_at = utcnow()

            await session.commit()
            logger.info(f"Session indítva: id={cs.id} cp={cp_id} connector={connector_id}")
            return int(cs.id)

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

            tx_str = str(transaction_id)

            # 1) normál: ocpp_transaction_id egyezés
            res = await session.execute(
                select(ChargeSession)
                .options(selectinload(ChargeSession.samples))
                .where(
                    and_(
                        ChargeSession.charge_point_id == cp.id,
                        ChargeSession.ocpp_transaction_id == tx_str,
                        ChargeSession.finished_at.is_(None),
                    )
                )
                .limit(1)
            )
            cs = res.scalar_one_or_none()

            # 2) fallback: ha a CP int-ként küldi és nálad session id-vel azonos
            if not cs:
                res2 = await session.execute(
                    select(ChargeSession)
                    .options(selectinload(ChargeSession.samples))
                    .where(
                        and_(
                            ChargeSession.charge_point_id == cp.id,
                            ChargeSession.id == int(transaction_id),
                            ChargeSession.finished_at.is_(None),
                        )
                    )
                    .limit(1)
                )
                cs = res2.scalar_one_or_none()

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