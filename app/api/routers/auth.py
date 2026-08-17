# app/api/routers/auth.py
"""
Jelszó nélküli bejelentkezés email-kóddal (OTP), a mentett SZÁMLÁZÁSI profil
lekéréséhez. Kártyaadatot sehol nem tárolunk és nem kérünk itt.

Folyamat:
  1) POST /auth/request-code {email}      → 6 jegyű kód emailben
  2) POST /auth/verify-code {email, code} → { token, profile }
  3) GET  /auth/profile   (Bearer token)  → { profile }   (autofill-hez)
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import LoginCode, User
from app.ocpp.time_utils import utcnow
from app.services.auth_tokens import (
    CODE_MAX_ATTEMPTS,
    CODE_RESEND_COOLDOWN_S,
    CODE_TTL_S,
    generate_code,
    hash_code,
    issue_token,
    verify_code_hash,
    verify_token,
)
from app.services.email import send_login_code_email

logger = logging.getLogger("auth")

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _profile_dict(u: Optional[User]) -> Optional[dict]:
    if u is None:
        return None
    return {
        "email": u.email,
        "billing_type": u.billing_type,
        "billing_name": u.billing_name,
        "billing_street": u.billing_street,
        "billing_zip": u.billing_zip,
        "billing_city": u.billing_city,
        "billing_country": u.billing_country,
        "billing_company": u.billing_company,
        "billing_tax_number": u.billing_tax_number,
    }


async def _load_user(db: AsyncSession, email: str) -> Optional[User]:
    res = await db.execute(select(User).where(User.email == _norm_email(email)))
    return res.scalar_one_or_none()


async def upsert_user_profile(db: AsyncSession, email: str, fields: dict) -> User:
    """A mentett számlázási profil létrehozása/frissítése email alapján.

    Nem commitál – a hívó tranzakciójának része. Csak a nem-None mezőket írja felül.
    """
    email = _norm_email(email)
    user = await _load_user(db, email)
    if user is None:
        user = User(email=email)
        db.add(user)
    for key, val in fields.items():
        if val is not None:
            setattr(user, key, val)
    user.updated_at = utcnow()
    return user


async def get_current_email(
    authorization: Optional[str] = Header(None),
) -> str:
    """Bearer token → email. 401, ha hiányzik/érvénytelen/lejárt."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token = authorization.split(" ", 1)[1].strip()
    email = verify_token(token)
    if not email:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return email


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RequestCodeIn(BaseModel):
    email: EmailStr


class VerifyCodeIn(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=8)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/request-code", response_model=dict)
async def request_code(body: RequestCodeIn, db: AsyncSession = Depends(get_db)):
    """Kód küldése. A válasz nem árulja el, létezik-e fiók (enumeráció-védelem)."""
    email = _norm_email(str(body.email))
    now = utcnow()

    # Anti-spam: ha nemrég ment kód, ne küldjünk újat (de a válasz ok marad)
    res = await db.execute(
        select(LoginCode)
        .where(LoginCode.email == email)
        .order_by(desc(LoginCode.created_at))
        .limit(1)
    )
    last = res.scalar_one_or_none()
    if last and (now - last.created_at).total_seconds() < CODE_RESEND_COOLDOWN_S:
        logger.info("request-code cooldown hit email=%s", email)
        return {"ok": True, "cooldown_s": CODE_RESEND_COOLDOWN_S}

    code = generate_code()
    lc = LoginCode(
        email=email,
        code_hash=hash_code(email, code),
        expires_at=now + timedelta(seconds=CODE_TTL_S),
        attempts=0,
    )
    db.add(lc)
    await db.commit()

    sent = await send_login_code_email(to=email, code=code)
    if not sent:
        logger.warning("Login code email NOT sent (email service?) email=%s", email)
    return {"ok": True, "ttl_s": CODE_TTL_S}


@router.post("/verify-code", response_model=dict)
async def verify_code(body: VerifyCodeIn, db: AsyncSession = Depends(get_db)):
    email = _norm_email(str(body.email))
    now = utcnow()

    res = await db.execute(
        select(LoginCode)
        .where(
            LoginCode.email == email,
            LoginCode.consumed_at.is_(None),
            LoginCode.expires_at > now,
        )
        .order_by(desc(LoginCode.created_at))
        .limit(1)
    )
    lc = res.scalar_one_or_none()
    if lc is None:
        raise HTTPException(status_code=400, detail="code_invalid_or_expired")

    if lc.attempts >= CODE_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="too_many_attempts")

    lc.attempts += 1

    if not verify_code_hash(email, str(body.code), lc.code_hash):
        await db.commit()  # próbálkozás számláló mentése
        raise HTTPException(
            status_code=400,
            detail={"error": "code_incorrect", "attempts_left": max(0, CODE_MAX_ATTEMPTS - lc.attempts)},
        )

    # Siker: kód elhasználva, token kiadva, profil visszaadva
    lc.consumed_at = now
    user = await _load_user(db, email)
    await db.commit()

    token = issue_token(email)
    return {"ok": True, "token": token, "profile": _profile_dict(user)}


@router.get("/profile", response_model=dict)
async def get_profile(
    email: str = Depends(get_current_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _load_user(db, email)
    return {"ok": True, "profile": _profile_dict(user)}
