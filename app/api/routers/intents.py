from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import ChargePoint, ChargingIntent

logger = logging.getLogger("intents")

router = APIRouter(prefix="/intents", tags=["intents"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing env: {name}")
    return v


class CreateIntentIn(BaseModel):
    charge_point_id: int = Field(..., ge=1)
    connector_id: int = Field(1, ge=0)  # 0 is lehet (szimulátor)
    email: EmailStr
    hold_amount_huf: int = Field(5000, ge=1000, le=25000)


@router.post("/", response_model=dict)
async def create_intent(body: CreateIntentIn, db: AsyncSession = Depends(get_db)):
    # 1) CP ellenőrzés
    cp = (
        (await db.execute(select(ChargePoint).where(ChargePoint.id == body.charge_point_id)))
        .scalar_one_or_none()
    )
    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint not found")

    if (cp.status or "").lower() != "available":
        raise HTTPException(
            status_code=409,
            detail={"error": "charge_point_not_available", "status": cp.status},
        )

    # 2) Intent létrehozás DB-ben (CSAK létező oszlopokkal)
    intent = ChargingIntent(
        charge_point_id=cp.id,
        connector_id=int(body.connector_id),
        anonymous_email=str(body.email),
        status="pending_payment",
        hold_amount_huf=int(body.hold_amount_huf),
        expires_at=_utcnow() + timedelta(minutes=15),
    )
    db.add(intent)
    await db.commit()
    await db.refresh(intent)

    # 3) Stripe Checkout Session
    try:
        stripe.api_key = _get_env("STRIPE_SECRET_KEY")
        base_url = _get_env("PUBLIC_BASE_URL").rstrip("/")

        meta = {
            "intent_id": str(intent.id),
            "charge_point_id": str(cp.id),
            "connector_id": str(body.connector_id),
        }

        params = {
            "mode": "payment",
            "success_url": f"{base_url}/pay/success?intent_id={intent.id}",
            "cancel_url": f"{base_url}/pay/cancel?intent_id={intent.id}",
            "customer_email": str(body.email),
            "client_reference_id": str(intent.id),
            "metadata": meta,
            "line_items": [
                {
                    "price_data": {
                        "currency": "huf",
                        "product_data": {"name": "EV charging hold (deposit)"},
                        "unit_amount": int(body.hold_amount_huf) * 100,
                    },
                    "quantity": 1,
                }
            ],
            "payment_intent_data": {"metadata": meta},
        }

        # Stripe-python v14.x: create(**params). Idempotency request option keywordként.
        checkout = stripe.checkout.Session.create(
            **params,
            idempotency_key=f"intent:{intent.id}",
        )

    except Exception as e:
        logger.exception("stripe_checkout_create_failed intent_id=%s cp_id=%s", intent.id, cp.id)
        await db.rollback()
        # próbáljuk eltárolni a hibát
        try:
            intent.status = "failed"
            intent.last_error = str(e)[:255]
            intent.updated_at = _utcnow()
            await db.commit()
        except Exception:
            await db.rollback()
        raise HTTPException(
            status_code=502,
            detail={"error": "stripe_checkout_create_failed", "reason": str(e)},
        )

    # 4) Intent frissítés (CSAK létező oszlopok)
    intent.payment_provider = "stripe"
    intent.payment_provider_ref = checkout.get("id")
    intent.updated_at = _utcnow()
    await db.commit()

    return {
        "intent_id": intent.id,
        "checkout_url": checkout.get("url"),
        "expires_at": intent.expires_at.isoformat(),
    }
