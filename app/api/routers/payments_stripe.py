# app/api/routers/payments_stripe.py
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Optional, Tuple

from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from app.db.session import AsyncSessionLocal
from app.ocpp.registry import remote_start_transaction
from app.ocpp.time_utils import utcnow

logger = logging.getLogger("payments.stripe")

router = APIRouter(prefix="/payments/stripe", tags=["payments"])

# ---------------------------------------------------------------------
# Config / helpers
# ---------------------------------------------------------------------


def _get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing env: {name}")
    return v


def _parse_stripe_sig_header(sig_header: str) -> Tuple[Optional[int], list[str]]:
    """
    Stripe-Signature: t=...,v1=...,v1=...
    """
    t: Optional[int] = None
    v1_list: list[str] = []
    for part in (sig_header or "").split(","):
        part = part.strip()
        if part.startswith("t="):
            try:
                t = int(part[2:])
            except Exception:
                t = None
        elif part.startswith("v1="):
            v1_list.append(part[3:])
    return t, v1_list


def _compute_v1(secret: str, timestamp: int, payload: bytes) -> str:
    signed_payload = str(timestamp).encode("utf-8") + b"." + payload
    return hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()


def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str, tolerance_s: int = 300) -> None:
    """
    Minimal, library-free signature verification (v1, HMAC-SHA256).
    """
    if not sig_header:
        raise HTTPException(status_code=400, detail="missing_stripe_signature_header")

    ts, v1_list = _parse_stripe_sig_header(sig_header)
    if ts is None or not v1_list:
        raise HTTPException(status_code=400, detail="invalid_stripe_signature_header")

    now = int(time.time())
    if abs(now - ts) > tolerance_s:
        raise HTTPException(status_code=400, detail="stripe_signature_timestamp_out_of_tolerance")

    expected = _compute_v1(secret, ts, payload)
    if not any(hmac.compare_digest(expected, v1) for v1 in v1_list):
        raise HTTPException(status_code=400, detail="invalid_stripe_signature")


def _generate_stop_code() -> str:
    # 8 karakter, könnyen diktálható
    return secrets.token_hex(4).upper()


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


async def _load_intent(db: AsyncSession, intent_id: int) -> Optional[ChargingIntent]:
    res = await db.execute(select(ChargingIntent).where(ChargingIntent.id == intent_id))
    return res.scalar_one_or_none()


async def _load_cp(db: AsyncSession, cp_id: int) -> Optional[ChargePoint]:
    res = await db.execute(select(ChargePoint).where(ChargePoint.id == cp_id))
    return res.scalar_one_or_none()


async def _get_existing_session_for_intent(db: AsyncSession, intent_id: int) -> Optional[ChargeSession]:
    res = await db.execute(select(ChargeSession).where(ChargeSession.intent_id == intent_id).limit(1))
    return res.scalar_one_or_none()


async def _ensure_session_and_remote_start(db: AsyncSession, intent: ChargingIntent, checkout_session_id: str) -> dict:
    """
    Idempotens: ugyanarra az intentre csak 1 session lehet.
    Webhook retry esetén nem hozunk létre új sessiont.
    """

    # 0) intent státusz frissítése (idempotensen)
    if intent.status != "paid":
        intent.status = "paid"
    intent.payment_provider = intent.payment_provider or "stripe"
    intent.payment_provider_ref = checkout_session_id
    intent.updated_at = utcnow()

    # 1) ha már van session ehhez az intenthez -> csak visszatérünk
    existing = await _get_existing_session_for_intent(db, intent.id)
    if existing:
        logger.info(f"Webhook idempotent hit: intent_id={intent.id} session_id={existing.id}")
        return {"session_id": existing.id, "created": False}

    # 2) új session + stop code
    stop_code = _generate_stop_code()
    stop_hash = _hash_code(stop_code)

    cs = ChargeSession(
        charge_point_id=intent.charge_point_id,
        connector_id=intent.connector_id,
        ocpp_transaction_id=None,
        user_tag=None,
        started_at=utcnow(),
        finished_at=None,
        meter_start_wh=None,
        meter_stop_wh=None,
        energy_kwh=None,
        cost_huf=None,
        anonymous_email=intent.anonymous_email,
        intent_id=intent.id,
        stop_code_hash=stop_hash,
    )
    db.add(cs)
    await db.flush()  # kap id-t

    # 3) OCPP remote start (nem atomikusan a DB-vel, de webhook oldalról oké)
    cp = await _load_cp(db, intent.charge_point_id)
    if not cp:
        logger.error(f"ChargePoint not found for intent_id={intent.id} cp_id={intent.charge_point_id}")
        # itt nem dobunk, mert a payment már megtörtént; majd kezeljük refund/timeout flow-val később
        logger.warning("RemoteStart skipped: missing ChargePoint")
        return {"session_id": cs.id, "created": True, "remote_start": "skipped_no_cp", "stop_code": stop_code}

    try:
        ocpp_res = await remote_start_transaction(
            cp_id=str(cp.ocpp_id),
            connector_id=int(intent.connector_id),
            id_tag="ANON",
        )
        logger.info(f"RemoteStart result: intent_id={intent.id} session_id={cs.id} ocpp={ocpp_res}")
    except Exception as e:
        # payment után ne 500-azzunk webhookban: Stripe retry + log, később retry worker/ops
        logger.exception(f"RemoteStart failed: intent_id={intent.id} session_id={cs.id} err={e}")
        ocpp_res = {"status": "Error", "reason": str(e)}

    # TODO (következő kör): email stop_code elküldés
    # FONTOS: stop_code plaintext-et DB-be nem írunk, csak logba se kéne élesben.
    logger.info(f"STOP_CODE (TEMP LOG): intent_id={intent.id} session_id={cs.id} code={stop_code}")

    return {"session_id": cs.id, "created": True, "remote_start": ocpp_res, "stop_code": stop_code}


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------


@router.get("/health")
async def health():
    return {"ok": True, "service": "stripe"}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    # 1) env + signature verify
    try:
        secret = _get_env("STRIPE_WEBHOOK_SECRET")
    except RuntimeError as e:
        logger.error(str(e))
        raise HTTPException(status_code=503, detail="stripe_webhook_not_configured")

    payload = await request.body()
    _verify_stripe_signature(payload, stripe_signature or "", secret)

    # 2) parse event
    try:
        event: dict[str, Any] = json.loads(payload.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    event_id = event.get("id")
    event_type = event.get("type")
    data_obj = (event.get("data") or {}).get("object") or {}

    logger.info(f"Stripe webhook received: id={event_id} type={event_type}")

    # 3) handle only what we actually use
    if event_type != "checkout.session.completed":
        return {"ok": True}

    checkout_session_id = data_obj.get("id")
    payment_status = data_obj.get("payment_status")
    metadata = data_obj.get("metadata") or {}

    # Stripe oldalról completed, de safety: csak paid esetén induljon
    if payment_status not in (None, "paid"):  # néha nincs itt, de a completed tipikusan paid
        logger.warning(f"checkout.session.completed but payment_status={payment_status} event_id={event_id}")
        return {"ok": True}

    intent_id_raw = metadata.get("intent_id")
    if not intent_id_raw:
        logger.warning(f"Missing intent_id in metadata. event_id={event_id} checkout={checkout_session_id}")
        return {"ok": True}

    try:
        intent_id = int(intent_id_raw)
    except Exception:
        logger.warning(f"Invalid intent_id in metadata: {intent_id_raw}")
        return {"ok": True}

    # 4) DB transaction
    async with AsyncSessionLocal() as db:
        intent = await _load_intent(db, intent_id)
        if not intent:
            logger.warning(f"Intent not found: intent_id={intent_id} event_id={event_id}")
            return {"ok": True}

        # Expired intentet nem indítunk
        now = utcnow()
        if intent.expires_at and intent.expires_at < now:
            logger.warning(f"Intent expired: intent_id={intent.id} expires_at={intent.expires_at}")
            # itt később: refund flow
            intent.status = "expired"
            intent.updated_at = now
            await db.commit()
            return {"ok": True}

        result = await _ensure_session_and_remote_start(db, intent, str(checkout_session_id or ""))

        await db.commit()

    return {"ok": True, "handled": "checkout.session.completed", **result}