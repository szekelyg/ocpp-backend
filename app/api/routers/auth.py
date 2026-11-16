# app/api/routers/auth.py
"""
Belépés az ev-n: egyetlen fiókos út van, az egységes Energiafelhő-fiók (Keycloak).

  GET /auth/keycloak/config  → a SPA ebből indítja az Authorization Code + PKCE folyamatot;
                               a kapott access tokent Bearer-ként küldi (lásd docs/KEYCLOAK.md).

A mentett számlázási profilt a GET /api/me adja (app/api/routers/me.py); ez a modul csak a
profil mentését (upsert_user_profile) tartja.

A régi, saját e-mail-kódos belépés (POST /auth/request-code, POST /auth/verify-code)
2026-09-22-én megszűnt (TERV-egy-fiok, C. fázis): a két végpont HTTP 410-et ad, kódot
nem küldünk és nem ellenőrzünk. A korábban kiadott v1 e-mail-tokenek 2026-10-22-én lejártak,
a kódjuk és a csak azokat fogadó GET /auth/profile törölve. A vendég-töltés és a töltés utáni
nyugta-link (v1i intent-token) ettől független, változatlan.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.ocpp.time_utils import utcnow

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
