# app/ocpp/handlers/transactions.py
from __future__ import annotations

import logging
import os
from typing import Optional

import stripe

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from datetime import timezone

from app.ocpp.time_utils import parse_ocpp_timestamp, utcnow
from app.ocpp.ocpp_utils import _as_float, _as_int, _price_huf_per_kwh
from app.services.email import send_receipt_email
from app.services.invoice import create_session_invoice

logger = logging.getLogger("ocpp")

# HUF Stripe minimum – ennél kisebb összeget nem lehet capture-ölni
_STRIPE_MIN_HUF = 1000


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

            # 0) Ha már van nyitott, de még nem kapott ocpp_transaction_id-t,
            # akkor azt használjuk (dupla session védelem).
            res_existing = await session.execute(
                select(ChargeSession)
                .where(
                    and_(
                        ChargeSession.charge_point_id == cp.id,
                        ChargeSession.finished_at.is_(None),
                        ChargeSession.connector_id == connector_id,
                        ChargeSession.ocpp_transaction_id.is_(None),
                    )
                )
                .order_by(ChargeSession.id.desc())
                .limit(1)
            )
            existing = res_existing.scalar_one_or_none()

            if existing:
                cs = existing
                cs.user_tag = id_tag if isinstance(id_tag, str) else cs.user_tag
                cs.started_at = ts  # ez az OCPP "igazi" indulás ideje
                cs.meter_start_wh = meter_start
                cs.ocpp_transaction_id = str(cs.id)  # nálunk txId = session.id
                logger.info(f"StartTransaction: REUSE existing session id={cs.id} cp={cp_id} connector={connector_id}")
            else:
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
                cs.ocpp_transaction_id = str(cs.id)
                logger.info(f"StartTransaction: NEW session id={cs.id} cp={cp_id} connector={connector_id}")

            # Azonnali 0 kWh / 0 Ft megjelenítés a UI-ban (MeterValues az első ~60mp-ben még nem jön)
            cs.energy_kwh = 0.0
            price = _price_huf_per_kwh()
            if price is not None:
                cs.cost_huf = 0.0

            # cp.status-t NEM állítjuk "charging"-re – a töltő hamarosan küld StatusNotification
            # "Charging" üzenetet, amikor ténylegesen megkezdődik az áramszolgáltatás.
            # Addig a UI "connecting" fázist mutat (ocpp_transaction_id van, de cp.status != "charging").
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
                .options(
                    selectinload(ChargeSession.samples),
                    selectinload(ChargeSession.intent),
                )
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

            # 2) Mismatch fallback: meter_start_wh >> meter_stop_wh
            # Ez akkor fordul elő, ha a töltő lifetime countert küldött MeterValues-ban
            # (pl. 59206 Wh) de session-relative értéket StopTransaction-ban (pl. 455 Wh).
            # Ilyenkor a meterStop közvetlenül a session energiáját jelenti (meterStart=0 volt eredetileg).
            if (cs.energy_kwh is None or cs.energy_kwh == 0.0) and meter_stop is not None:
                start_wh = float(cs.meter_start_wh) if cs.meter_start_wh is not None else 0.0
                stop_wh = float(meter_stop)
                if start_wh > stop_wh > 0 and stop_wh < 100_000:
                    cs.energy_kwh = stop_wh / 1000.0
                    price = _price_huf_per_kwh()
                    if price is not None:
                        cs.cost_huf = cs.energy_kwh * float(price)
                    logger.info(
                        f"StopTransaction mismatch fallback: meter_start={start_wh:.0f} > meter_stop={stop_wh:.0f} "
                        f"→ energy={cs.energy_kwh:.3f} kWh session_id={cs.id}"
                    )

            # 3) fallback: sample-alapú, ha nincs meterStart
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

            # cp.status-t NEM állítjuk "available"-re – a töltő hamarosan küld
            # StatusNotification-t a tényleges fizikai állapottal (pl. "preparing"
            # ha az autó még be van dugva). Azt a save_status_notification kezeli.
            cp.last_seen_at = utcnow()

            await session.commit()
            logger.info(
                f"Session lezárva: id={cs.id} tx={transaction_id} meter_stop_wh={meter_stop} "
                f"energy_kwh={cs.energy_kwh} cost_huf={cs.cost_huf}"
            )

            # Receipt email – csak ha van email cím (fizetésen keresztül indított session)
            if cs.anonymous_email:
                duration_s = None
                if cs.started_at and cs.finished_at:
                    start = cs.started_at if cs.started_at.tzinfo else cs.started_at.replace(tzinfo=timezone.utc)
                    end = cs.finished_at if cs.finished_at.tzinfo else cs.finished_at.replace(tzinfo=timezone.utc)
                    duration_s = max(0, int((end - start).total_seconds()))
                intent = cs.intent
                await send_receipt_email(
                    to=cs.anonymous_email,
                    session_id=cs.id,
                    cp_ocpp_id=cp_id,
                    duration_s=duration_s,
                    energy_kwh=cs.energy_kwh,
                    cost_huf=cs.cost_huf,
                    billing_name=intent.billing_name if intent else None,
                    billing_type=intent.billing_type if intent else None,
                    billing_company=intent.billing_company if intent else None,
                    billing_tax_number=intent.billing_tax_number if intent else None,
                    billing_street=intent.billing_street if intent else None,
                    billing_zip=intent.billing_zip if intent else None,
                    billing_city=intent.billing_city if intent else None,
                    billing_country=intent.billing_country if intent else None,
                )

            # Stripe capture / cancel
            await _stripe_settle(cs)

            # Számla kiállítása (csak Stripe-on indított, emailes session)
            if cs.anonymous_email and cs.intent:
                captured_huf = _captured_amount(cs)
                if captured_huf and captured_huf > 0:
                    invoice_number = await create_session_invoice(
                        session_id=cs.id,
                        energy_kwh=cs.energy_kwh,
                        captured_huf=captured_huf,
                        cp_ocpp_id=cp_id,
                        buyer_email=cs.anonymous_email,
                        buyer_name=cs.intent.billing_name,
                        buyer_zip=cs.intent.billing_zip,
                        buyer_city=cs.intent.billing_city,
                        buyer_street=cs.intent.billing_street,
                        buyer_country=cs.intent.billing_country,
                        buyer_tax_number=cs.intent.billing_tax_number,
                        buyer_company=cs.intent.billing_company,
                        billing_type=cs.intent.billing_type,
                    )
                    if invoice_number:
                        cs.invoice_number = invoice_number
                        async with AsyncSessionLocal() as upd:
                            await upd.execute(
                                __import__("sqlalchemy").text(
                                    "UPDATE charge_sessions SET invoice_number=:inv WHERE id=:sid"
                                ),
                                {"inv": invoice_number, "sid": cs.id},
                            )
                            await upd.commit()

    except Exception as e:
        logger.exception(f"Hiba StopTransaction mentésekor: {e}")


def _captured_amount(cs: ChargeSession) -> float:
    """Ténylegesen levont összeg HUF-ban (ugyanaz a logika mint _stripe_settle-ben)."""
    cost = cs.cost_huf or 0.0
    hold = (cs.intent.hold_amount_huf or 0) if cs.intent else 0
    if cost <= 0:
        return 0.0
    captured = max(_STRIPE_MIN_HUF, round(cost))
    captured = min(captured, hold)
    return float(captured)


async def _stripe_settle(cs: ChargeSession) -> None:
    """
    Manual capture flow: a töltés végén vagy capture-öljük a tényleges összeget,
    vagy cancel-eljük az authorizationt (0 Ft vagy minimum alatt).
    """
    intent = cs.intent
    if not intent or not intent.stripe_payment_intent_id:
        return  # nem Stripe-on indított session

    pi_id = intent.stripe_payment_intent_id
    cost = cs.cost_huf or 0.0
    hold = intent.hold_amount_huf or 0

    sk = os.environ.get("STRIPE_SECRET_KEY")
    if not sk:
        logger.error("_stripe_settle: STRIPE_SECRET_KEY nincs beállítva, capture/cancel kihagyva")
        return

    stripe.api_key = sk

    try:
        if cost <= 0:
            # Semmi nem töltődött → teljes felszabadítás, nincs terhelés
            stripe.PaymentIntent.cancel(pi_id)
            logger.info(f"Stripe cancel: pi={pi_id} cost_huf={cost:.2f} session_id={cs.id}")
        else:
            # Bármennyi energia felhasználva → levonás.
            # Stripe HUF minimum = 175 Ft; ha a díj ez alatt van, legalább 175 Ft-ot vonunk le.
            capture_huf = max(_STRIPE_MIN_HUF, round(cost))
            capture_huf = min(capture_huf, hold)  # nem haladhatja meg a zárolást
            capture_filler = capture_huf * 100     # Stripe fillérben számolja a HUF-ot
            stripe.PaymentIntent.capture(pi_id, amount_to_capture=capture_filler)
            logger.info(
                f"Stripe capture: pi={pi_id} capture_huf={capture_huf} "
                f"(cost={cost:.2f}, min={_STRIPE_MIN_HUF}, hold={hold}) session_id={cs.id}"
            )
    except stripe.error.InvalidRequestError as e:
        # pl. már cancel-elve / capture-ölve van (idempotens retry esetén)
        logger.warning(f"Stripe settle InvalidRequest: pi={pi_id} err={e} session_id={cs.id}")
    except Exception as e:
        logger.exception(f"Stripe settle hiba: pi={pi_id} session_id={cs.id} err={e}")