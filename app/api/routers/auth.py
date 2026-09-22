# app/api/routers/auth.py
"""
Belépés az ev-n: egyetlen fiókos út van, az egységes Energiafelhő-fiók (Keycloak).

  GET /auth/keycloak/config  → a SPA ebből indítja az Authorization Code + PKCE folyamatot;
                               a kapott access tokent Bearer-ként küldi (lásd docs/KEYCLOAK.md).
  GET /auth/profile          → a mentett SZÁMLÁZÁSI profil (Bearer). Kártyaadatot sehol nem
                               tárolunk és nem kérünk.

A régi, saját e-mail-kódos belépés (POST /auth/request-code, POST /auth/verify-code)
2026-09-22-én megszűnt (TERV-egy-fiok, C. fázis): a két végpont HTTP 410-et ad, kódot
nem küldünk és nem ellenőrzünk. A korábban kiadott v1 e-mail-tokeneket a Bearer-t fogadó
végpontok a lejáratukig (30 nap) még elfogadják – lásd app.api.deps. A vendég-töltés és a
töltés utáni nyugta-link (v1i intent-token) ettől független, változatlan.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import User
from app.ocpp.time_utils import utcnow
from app.services.auth_tokens import verify_token

logger = logging.getLogger("auth")

router = APIRouter(prefix="/auth", tags=["auth"])

RETIRED_LOGIN = {
    "error": "retired",
    "message": "A régi e-mail-kódos belépés megszűnt. Lépj be az Energiafelhő-fiókoddal.",
}


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
    """Bearer (v1 e-mail-token) → email. 401, ha hiányzik/érvénytelen/lejárt."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    token = authorization.split(" ", 1)[1].strip()
    email = verify_token(token)
    if not email:
        raise HTTPException(status_code=401, detail="invalid_or_expired_token")
    return email


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/request-code", status_code=410, response_model=dict)
@router.post("/verify-code", status_code=410, response_model=dict)
async def retired_email_code_login():
    """Megszűnt e-mail-kódos belépés: mindig 410, a body-t nem is olvassuk."""
    return JSONResponse(status_code=410, content=RETIRED_LOGIN)


@router.get("/keycloak/config", response_model=dict)
async def keycloak_config():
    """A SPA Keycloak-belépéséhez szükséges, nem titkos OIDC adatok (PKCE public kliens).

    Nincs KEYCLOAK_ISSUER → {"enabled": false}, és a frontend nem mutatja a gombot.
    """
    from app.services.keycloak import public_config
    return await public_config()


@router.get("/profile", response_model=dict)
async def get_profile(
    email: str = Depends(get_current_email),
    db: AsyncSession = Depends(get_db),
):
    user = await _load_user(db, email)
    return {"ok": True, "profile": _profile_dict(user)}
