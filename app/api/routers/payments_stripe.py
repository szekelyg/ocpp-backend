# app/api/routers/payments_stripe.py
from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request

logger = logging.getLogger("payments.stripe")

router = APIRouter(prefix="/payments/stripe", tags=["payments"])

@router.get("/health")
async def health():
    return {"ok": True, "service": "stripe"}


def _get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing env: {name}")
    return v


def _parse_stripe_sig_header(sig_header: str) -> tuple[Optional[int], list[str]]:
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
    mac = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return mac


def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str, tolerance_s: int = 300) -> None:
    if not sig_header:
        raise HTTPException(status_code=400, detail="missing_stripe_signature_header")

    ts, v1_list = _parse_stripe_sig_header(sig_header)
    if ts is None or not v1_list:
        raise HTTPException(status_code=400, detail="invalid_stripe_signature_header")

    now = int(time.time())
    if abs(now - ts) > tolerance_s:
        raise HTTPException(status_code=400, detail="stripe_signature_timestamp_out_of_tolerance")

    expected = _compute_v1(secret, ts, payload)

    # több v1 is lehet, bármelyik jó
    ok = any(hmac.compare_digest(expected, v1) for v1 in v1_list)
    if not ok:
        raise HTTPException(status_code=400, detail="invalid_stripe_signature")


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
):
    """
    Stripe webhook receiver.
    Most: signature verify + event parse + log + 200.
    Később itt fogjuk: ChargingIntent paid -> ChargeSession létrehozás -> RemoteStartTransaction.
    """
    try:
        secret = _get_env("STRIPE_WEBHOOK_SECRET")
    except RuntimeError as e:
        logger.error(str(e))
        raise HTTPException(status_code=503, detail="stripe_webhook_not_configured")

    payload = await request.body()
    _verify_stripe_signature(payload, stripe_signature or "", secret)

    try:
        event = json.loads(payload.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    event_id = event.get("id")
    event_type = event.get("type")

    data_obj = (event.get("data") or {}).get("object") or {}
    logger.info(f"Stripe webhook received: id={event_id} type={event_type}")

    # MVP: csak ezt figyeljük, később bővítjük (refund/expired/etc.)
    if event_type == "checkout.session.completed":
        # fontos mezők (Stripe Checkout Session)
        session_id = data_obj.get("id")
        payment_status = data_obj.get("payment_status")
        amount_total = data_obj.get("amount_total")  # minor unit (pl. HUF fillér nincs, de Stripe így adja)
        currency = data_obj.get("currency")
        metadata = data_obj.get("metadata") or {}

        logger.info(
            "checkout.session.completed: "
            f"session_id={session_id} payment_status={payment_status} amount_total={amount_total} currency={currency} metadata={metadata}"
        )

        # TODO (következő lépés):
        # - metadata.intent_id alapján ChargingIntent status=paid
        # - létrehoz ChargeSession + stop_code
        # - RemoteStartTransaction

    return {"ok": True}