# app/ocpp/handlers/reconnect.py
"""
Ha egy töltő visszacsatlakozik, és van nyitott session ami RemoteStart-ra vár
(ocpp_transaction_id IS NULL, finished_at IS NULL, <15 perc), újraküldjük
a RemoteStartTransaction parancsot.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import and_, select

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, ChargeSession
from app.ocpp.time_utils import utcnow
from app.ocpp.registry import remote_start_transaction

logger = logging.getLogger("ocpp")

_RECONNECT_DELAY_S = 2.0   # annyi idő a töltőnek hogy stabilizálódjon
_SESSION_MAX_AGE_MIN = 14  # 15 perces waiting timeout előtt 1 perccel adjuk fel


async def retry_pending_remote_start(cp_id: str) -> None:
    """
    Aszinkron task: rövid várakozás után megnézi van-e pending session,
    és ha igen, újraküldi a RemoteStart-ot.
    Csak egyszer fut le (BootNotification triggereli).
    """
    await asyncio.sleep(_RECONNECT_DELAY_S)

    try:
        async with AsyncSessionLocal() as db:
            cp = (
                await db.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))
            ).scalar_one_or_none()

            if not cp:
                return

            cutoff = utcnow() - timedelta(minutes=_SESSION_MAX_AGE_MIN)

            res = await db.execute(
                select(ChargeSession)
                .where(
                    and_(
                        ChargeSession.charge_point_id == cp.id,
                        ChargeSession.finished_at.is_(None),
                        ChargeSession.ocpp_transaction_id.is_(None),
                        ChargeSession.started_at > cutoff,
                    )
                )
                .order_by(ChargeSession.started_at.desc())
                .limit(1)
            )
            pending = res.scalar_one_or_none()

            if not pending:
                logger.debug(f"Reconnect: nincs pending session, cp={cp_id}")
                return

            logger.info(
                f"Reconnect: pending session találva id={pending.id} cp={cp_id} "
                f"connector={pending.connector_id} – RemoteStart újraküldés"
            )

        # DB session lezárva, most küldünk OCPP parancsot
        try:
            result = await remote_start_transaction(
                cp_id=cp_id,
                connector_id=int(pending.connector_id or 1),
                id_tag="ANON",
            )
            logger.info(
                f"Reconnect RemoteStart OK: session_id={pending.id} cp={cp_id} result={result}"
            )
        except Exception as e:
            logger.error(
                f"Reconnect RemoteStart FAILED: session_id={pending.id} cp={cp_id} err={e}"
            )

    except Exception as e:
        logger.exception(f"retry_pending_remote_start hiba: cp={cp_id} err={e}")
