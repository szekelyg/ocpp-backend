# app/ocpp/handlers/status.py
from __future__ import annotations

import logging
from sqlalchemy import select, and_

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, ChargeSession
from app.ocpp.time_utils import utcnow
from app.ocpp.ocpp_utils import _as_int
from app.ocpp.parsers import _normalize_cp_status

logger = logging.getLogger("ocpp")

# Connector 0 = állomás-szintű állapot; a tényleges csatlakozó (>=1) állapota a mérvadó.
# Aktív session alatt a connector 0 ezen "lefelé" jelzéseit nem engedjük felülírni
# (a charging/preparing/finishing státuszt a connector >=1 StatusNotification adja).
_CONNECTOR0_IGNORE_WHEN_ACTIVE = {"available", "unavailable"}


async def save_status_notification(cp_id: str, payload: dict) -> None:
    """
    StatusNotification payload tipikusan:
    { connectorId, status, errorCode, timestamp }
    """
    try:
        incoming = _normalize_cp_status(payload.get("status"))
        connector_id = _as_int(payload.get("connectorId"))

        async with AsyncSessionLocal() as session:
            cp = (
                await session.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))
            ).scalar_one_or_none()
            if not cp:
                return

            cp.last_seen_at = utcnow()

            # Van-e aktív (nyitott) session ezen a töltőn?
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

            # 1) Aktív session alatt az "available" sosem írja felül a státuszt.
            # 2) Aktív session alatt a connector 0 (állomás-szintű) available/unavailable
            #    jelzését sem vesszük figyelembe – a csatlakozó (>=1) a mérvadó.
            if active and (
                incoming == "available"
                or (connector_id == 0 and incoming in _CONNECTOR0_IGNORE_WHEN_ACTIVE)
            ):
                await session.commit()
                return

            cp.status = incoming
            cp.ocpi_last_updated = utcnow()
            loc_id = cp.location_id
            await session.commit()

        # OCPI: a státuszváltást best-effort továbbítjuk a regisztrált partnereknek
        from app.ocpi.services.push_service import schedule_push_location
        schedule_push_location(loc_id)

    except Exception as e:
        logger.exception(f"Hiba StatusNotification mentésekor: {e}")