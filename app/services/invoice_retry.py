# app/services/invoice_retry.py
"""
Kimaradt számlák pótlása háttérben.

Ha a töltés végén a Számlázz.hu nem volt elérhető (pl. 520-as hiba), a session
számlaszám nélkül marad. Ez a job időnként végignézi a lezárt, kifizetett,
emailes sessionöket, amelyeknek nincs számlaszámuk, és pótolja a számlát.

Dupla számla ellen: kiállítás előtt rendelésszám (= session id) alapján
lekérdezzük a Számlázz.hu-t; ha ott már van számla, csak a számlaszámot mentjük.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from app.db.session import AsyncSessionLocal
from app.ocpp.time_utils import utcnow
from app.services.invoice import create_session_invoice, find_invoice_number_by_order

logger = logging.getLogger("invoice")

# Ennyi idő után nézzük csak – a StopTransaction-ben futó azonnali kiállítás
# (retry-okkal együtt) addig még dolgozhat rajta.
_MIN_AGE = timedelta(minutes=5)
# Ennél régebbi sessionöket nem bolygatjuk automatikusan (admin kézzel pótolhatja).
_MAX_AGE = timedelta(days=30)
# Egy körben legfeljebb ennyit próbálunk, hogy kimaradás után ne zúdítsunk rá mindent.
_BATCH = 5


async def retry_missing_invoices_once() -> int:
    """Egy kör pótlás. Visszaadja a sikeresen bejegyzett számlák számát."""
    from app.ocpp.handlers.transactions import _captured_amount

    now = utcnow()
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(ChargeSession)
            .join(ChargingIntent, ChargingIntent.id == ChargeSession.intent_id)
            .options(selectinload(ChargeSession.intent), selectinload(ChargeSession.charge_point))
            .where(
                ChargeSession.finished_at.isnot(None),
                ChargeSession.finished_at < now - _MIN_AGE,
                ChargeSession.finished_at > now - _MAX_AGE,
                ChargeSession.invoice_number.is_(None),
                ChargeSession.anonymous_email.isnot(None),
                ChargeSession.cost_huf > 0,
                ChargingIntent.status == "paid",
                ChargingIntent.stripe_payment_intent_id.isnot(None),
            )
            .order_by(ChargeSession.finished_at.asc())
            .limit(_BATCH)
        )
        sessions = res.scalars().all()
        if not sessions:
            return 0

        fixed = 0
        for cs in sessions:
            captured_huf = _captured_amount(cs)
            if captured_huf <= 0:
                continue

            # 1) Már létezik a Számlázz.hu-n? Akkor csak a számlaszám hiányzik.
            existing = await find_invoice_number_by_order(cs.id)
            if existing:
                cs.invoice_number = existing
                await db.commit()
                fixed += 1
                logger.info(f"Hiányzó számlaszám pótolva Számlázz.hu-ról: {existing} session_id={cs.id}")
                continue

            # 2) Nincs – kiállítjuk.
            intent = cs.intent
            cp_ocpp_id = cs.charge_point.ocpp_id if cs.charge_point else "—"
            logger.info(f"Kimaradt számla pótlása: session_id={cs.id} bruttó={captured_huf} HUF")
            invoice_number = await create_session_invoice(
                session_id=cs.id,
                energy_kwh=cs.energy_kwh,
                captured_huf=captured_huf,
                cp_ocpp_id=cp_ocpp_id,
                buyer_email=cs.anonymous_email,
                buyer_name=intent.billing_name,
                buyer_zip=intent.billing_zip,
                buyer_city=intent.billing_city,
                buyer_street=intent.billing_street,
                buyer_country=intent.billing_country,
                buyer_tax_number=intent.billing_tax_number,
                buyer_company=intent.billing_company,
                billing_type=intent.billing_type,
            )
            if invoice_number:
                cs.invoice_number = invoice_number
                await db.commit()
                fixed += 1
            else:
                # A create_session_invoice már logolta a hibát; a következő körben újra próbáljuk.
                break

        return fixed
