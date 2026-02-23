# app/ocpp/handlers/status.py
from __future__ import annotations

import logging
from sqlalchemy import select, and_

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, ChargeSession
from app.ocpp.time_utils import utcnow
from app.ocpp.parsers import _normalize_cp_status

logger = logging.getLogger("ocpp")


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