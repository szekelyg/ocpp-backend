# app/ocpp/handlers/heartbeat.py
from __future__ import annotations

import logging
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint
from app.ocpp.time_utils import utcnow

logger = logging.getLogger("ocpp")


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