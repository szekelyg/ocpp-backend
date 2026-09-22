from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta

import stripe
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, EmailStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Identity, get_db, get_optional_identity
from app.api.routers.charge_points import compute_status
from app.db.models import ChargePoint, ChargingIntent, User
from app.services.auth_tokens import issue_intent_token

logger = logging.getLogger("intents")

router = APIRouter(prefix="/intents", tags=["intents"])

# Anti-spam a nyilvános, hitelesítés nélküli végponton – ugyanaz a DB-alapú minta,
# mint az /auth/request-code cooldownja: egy e-mail-címről az intent élettartamán
# (15 perc) belül legfeljebb ennyi fizetési kísérlet indítható. Egy tisztességes
# felhasználónak ez bőven elég (a Stripe-oldalról visszalépve is új intent jön létre).
INTENT_RATE_WINDOW_S = 15 * 60
INTENT_RATE_MAX_PER_EMAIL = 10

# Stripe API key inicializálás egyszer, modulbetöltéskor
_stripe_key = os.environ.get("STRIPE_SECRET_KEY")
if _stripe_key:
    stripe.api_key = _stripe_key


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
    # Vendégnek kötelező. Bejelentkezve (Bearer: e-mail-token vagy Keycloak) a fiók e-mailje
    # számít, a body-beli értéket figyelmen kívül hagyjuk – a session így a fiókhoz kötődik.
    email: Optional[EmailStr] = None
    hold_amount_huf: int = Field(5000, ge=1000, le=25000)

    # Számlázás – mindig kötelező. Bejelentkezve a hiányzó mezők a users-beli mentett
    # profilból egészülnek ki (_billing_from_body_or_profile), vendégnek mind kell.
    billing_type: str = Field("personal", pattern=r"^(personal|business)$")
    billing_name: Optional[str] = Field(None, min_length=2, max_length=255)
    billing_street: Optional[str] = Field(None, min_length=2, max_length=255)
    billing_zip: Optional[str] = Field(None, min_length=2, max_length=16)
    billing_city: Optional[str] = Field(None, min_length=1, max_length=128)
    billing_country: Optional[str] = Field("HU", min_length=2, max_length=4)
    # Csak céges számlánál
    billing_company: str | None = Field(None, max_length=255)
    billing_tax_number: str | None = Field(None, max_length=64)

    # "Adataim mentése legközelebbre" pipa – a számlázási profilt emailhez kötve
    # elmentjük, hogy visszatérő belépéskor automatikusan kitöltődjön. Kártyaadat SOHA.
    save_profile: bool = False


_BILLING_REQUIRED = ("billing_name", "billing_street", "billing_zip", "billing_city", "billing_country")


async def _billing_from_body_or_profile(
    body: CreateIntentIn, ident: Optional[Identity], db: AsyncSession
) -> dict:
    """Számlázási mezők: a body-ból; bejelentkezve a hiányzók a mentett profilból. 422, ha így is hiányzik."""
    fields = {
        "billing_type": body.billing_type,
        "billing_name": body.billing_name,
        "billing_street": body.billing_street,
        "billing_zip": body.billing_zip,
        "billing_city": body.billing_city,
        "billing_country": body.billing_country,
        "billing_company": body.billing_company,
        "billing_tax_number": body.billing_tax_number,
    }
    if ident is not None and any(not fields[k] for k in _BILLING_REQUIRED):
        user = (await db.execute(select(User).where(User.email == ident.email))).scalar_one_or_none()
        if user is not None:
            for k in ("billing_name", "billing_street", "billing_zip", "billing_city", "billing_country"):
                if not fields[k]:
                    fields[k] = getattr(user, k)
            if body.billing_type == "business":
                fields["billing_company"] = fields["billing_company"] or user.billing_company
                fields["billing_tax_number"] = fields["billing_tax_number"] or user.billing_tax_number
    missing = [k for k in _BILLING_REQUIRED if not fields[k]]
    if missing:
        raise HTTPException(status_code=422, detail={"error": "billing_missing", "fields": missing})
    if fields["billing_type"] == "business":
        biz_missing = [k for k in ("billing_company", "billing_tax_number") if not fields[k]]
        if biz_missing:
            raise HTTPException(status_code=422, detail={"error": "billing_missing", "fields": biz_missing})
    else:
        fields["billing_company"] = None
        fields["billing_tax_number"] = None
    return fields


@router.post("/", response_model=dict)
async def create_intent(
    body: CreateIntentIn,
    db: AsyncSession = Depends(get_db),
    ident: Optional[Identity] = Depends(get_optional_identity),
):
    # 0) Kinek a nevében? Bejelentkezve (Keycloak / e-mail-token) a fiók e-mailje – SSO-felismerés.
    if ident is not None:
        email = ident.email
    elif body.email:
        email = str(body.email).strip().lower()
    else:
        raise HTTPException(status_code=422, detail={"error": "email_required"})
    billing = await _billing_from_body_or_profile(body, ident, db)

    # 1) CP ellenőrzés
    cp = (
        (await db.execute(select(ChargePoint).where(ChargePoint.id == body.charge_point_id)))
        .scalar_one_or_none()
    )
    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint not found")

    # Konfigurálásra váró (publikálatlan) töltőn nem indítható publikus fizetés.
    # Az admin teszt-töltés (/api/admin/charge-points/{id}/test-charge) szándékosan
    # kihagyja ezt az ellenőrzést: publikálás előtt kell tudni tesztelni.
    if not cp.is_published:
        raise HTTPException(status_code=404, detail="ChargePoint not found")

    # "available"  → autó még nincs bedugva, RemoteStart után a CP Preparing-be megy és vár
    # "preparing"  → autó már be van dugva, RemoteStart után azonnal indul a töltés
    # "finishing"  → Volite-specifikus: ezt jelenti amikor autó csatlakoztatva van (de még nem tölt)
    # minden más státusz (charging, faulted, offline, stb.) → nem indítható
    # FONTOS: compute_status() (nem a nyers cp.status), különben egy 2 percnél régebben
    # látott, valójában offline töltőre is el lehetne indítani a fizetést egy régóta
    # nyitva hagyott böngészőfülről.
    _startable = {"available", "preparing", "finishing"}
    status_now = compute_status(cp).lower()
    if status_now not in _startable:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "charge_point_not_available",
                "status": status_now,
                "startable_statuses": sorted(_startable),
            },
        )

    # 1b) E-mail-enkénti throttle (lásd INTENT_RATE_*)
    recent = (
        await db.execute(
            select(func.count())
            .select_from(ChargingIntent)
            .where(
                ChargingIntent.anonymous_email == email,
                ChargingIntent.created_at > _utcnow() - timedelta(seconds=INTENT_RATE_WINDOW_S),
            )
        )
    ).scalar_one()
    if recent >= INTENT_RATE_MAX_PER_EMAIL:
        logger.warning("intent rate limit hit email=%s recent=%s", email, recent)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "too_many_intents",
                "hint": "Túl sok fizetési kísérlet indult erről az e-mail-címről. Kérjük, próbálja újra néhány perc múlva.",
            },
        )

    # 2) Intent létrehozás DB-ben
    intent = ChargingIntent(
        charge_point_id=cp.id,
        connector_id=int(body.connector_id),
        anonymous_email=email,
        status="pending_payment",
        hold_amount_huf=int(body.hold_amount_huf),
        expires_at=_utcnow() + timedelta(minutes=15),
        **billing,
    )
    db.add(intent)

    # A "mentse az adataimat" pipa (save_profile) NEM itt ír a users táblába: ez a végpont
    # hitelesítés nélkül hívható, így bárki tetszőleges e-mail-címre hozhatna létre
    # profilt. A jelzőt a Stripe metadata viszi, és a profilt a sikeres fizetés
    # webhookja menti (payments_stripe.stripe_webhook) – tehát csak az kap profilt,
    # aki ténylegesen fizetett. Kártyaadat SOHA nem kerül ide – az a Stripe-nál marad.
    await db.commit()
    await db.refresh(intent)

    # 3) Stripe Checkout Session
    try:
        if not stripe.api_key:
            stripe.api_key = _get_env("STRIPE_SECRET_KEY")
        base_url = _get_env("PUBLIC_BASE_URL").rstrip("/")

        meta = {
            "intent_id": str(intent.id),
            "charge_point_id": str(cp.id),
            "connector_id": str(body.connector_id),
            "save_profile": "1" if body.save_profile else "0",
        }
        # Intent-token: ezzel bizonyítja a vendég a /api/sessions/{id}/stop-nál, hogy ő
        # indította a töltést. A success_url-lel jut vissza a böngészőbe.
        intent_token = issue_intent_token(intent.id)

        product_name = (
            "EV töltési előleg – céges számla"
            if billing["billing_type"] == "business"
            else "EV töltési előleg"
        )

        params = {
            "mode": "payment",
            "success_url": f"{base_url}/pay/success?intent_id={intent.id}&t={intent_token}",
            "cancel_url": f"{base_url}/pay/cancel?intent_id={intent.id}",
            "customer_email": email,
            "client_reference_id": str(intent.id),
            "metadata": meta,
            "line_items": [
                {
                    "price_data": {
                        "currency": "huf",
                        "product_data": {"name": product_name},
                        "unit_amount": int(body.hold_amount_huf) * 100,
                    },
                    "quantity": 1,
                }
            ],
            "payment_intent_data": {
                "metadata": meta,
                "capture_method": "manual",  # csak zárolás, tényleges terhelés a töltés végén
            },
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
