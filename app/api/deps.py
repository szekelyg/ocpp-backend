from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import AsyncGenerator, Literal, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal

logger = logging.getLogger("auth")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Bejelentkezett fiók: Keycloak access token (az egyetlen belépési út), VAGY egy még le
# nem járt, 2026-09-22 előtt kiadott v1 e-mail-token (a régi e-mail-kódos belépés megszűnt,
# újat nem adunk ki; a meglévők 30 napon belül maguktól lejárnak – akkor ez az ág törölhető).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Identity:
    email: str                                   # kisbetűs; a users / charge_sessions kulcsa
    source: Literal["email_token", "keycloak"]
    keycloak_sub: Optional[str] = None
    name: Optional[str] = None


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


async def _identity_from_token(token: str, db: AsyncSession) -> Identity:
    """Token → Identity. 401, ha érvénytelen; 403, ha a Keycloak e-mail nincs megerősítve."""
    from app.services import keycloak
    from app.services.auth_tokens import verify_token

    # 1) régi e-mail-token (v1.<b64>.<exp>.<sig>) – csak a lejáratukig, újat nem adunk ki
    if not keycloak.looks_like_jwt(token):
        email = verify_token(token)
        if not email:
            raise HTTPException(status_code=401, detail="invalid_or_expired_token")
        return Identity(email=email, source="email_token")

    # 2) Keycloak JWT
    try:
        kc = await keycloak.verify_access_token(token)
    except keycloak.KeycloakAuthError as e:
        logger.info("keycloak token elutasítva: %s", e.reason)
        raise HTTPException(status_code=401, detail=f"keycloak_{e.reason}")

    if not kc.email:
        raise HTTPException(status_code=401, detail="keycloak_email_claim_missing")
    if not kc.email_verified:
        # Megerősítetlen e-mailhez nem kötünk ev-fiókot, és nem mutatunk semmit
        raise HTTPException(status_code=403, detail="keycloak_email_not_verified")

    await _link_keycloak_user(db, email=kc.email, sub=kc.sub)
    return Identity(email=kc.email, source="keycloak", keycloak_sub=kc.sub, name=kc.name)


async def _link_keycloak_user(db: AsyncSession, email: str, sub: str) -> None:
    """users.keycloak_sub beállítása (első Keycloak-belépéskor). Csak megerősített e-maillel hívható."""
    from app.db.models import User
    from app.ocpp.time_utils import utcnow

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        db.add(User(email=email, keycloak_sub=sub))
    elif user.keycloak_sub is None:
        user.keycloak_sub = sub
        user.updated_at = utcnow()
    elif user.keycloak_sub != sub:
        # Ugyanaz az e-mail, MÁS Keycloak-alany: nem írjuk át csendben (fiók-átvétel ellen;
        # a portál és az app. ugyanígy elutasít). Csak törölt-újralétrehozott Keycloak-fióknál
        # fordulhat elő — akkor kézi rendezés kell.
        logger.warning("keycloak_sub ütközés: %s már más alanyhoz kötött, az új sub elutasítva", email)
        raise HTTPException(status_code=403, detail="keycloak_sub_mismatch")
    else:
        return
    try:
        await db.commit()
    except Exception:
        # pl. versenyhelyzet két párhuzamos első belépésnél – a következő kérés rendezi
        await db.rollback()
        logger.exception("keycloak_sub mentés sikertelen email=%s", email)


async def get_current_identity(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Identity:
    """Kötelező bejelentkezés. 401 token nélkül / érvénytelen tokennel."""
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing_bearer_token")
    return await _identity_from_token(token, db)


async def get_optional_identity(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
) -> Optional[Identity]:
    """Nem kötelező bejelentkezés: header nélkül None; érvénytelen tokennel 401 (fail-closed)."""
    token = _bearer(authorization)
    if not token:
        return None
    return await _identity_from_token(token, db)


async def email_from_authorization(authorization: Optional[str], db: AsyncSession) -> Optional[str]:
    """Header → e-mail vagy None (nem dob) – ott, ahol a Bearer csak egy a több bizonyíték közül."""
    token = _bearer(authorization)
    if not token:
        return None
    try:
        return (await _identity_from_token(token, db)).email
    except HTTPException:
        return None
