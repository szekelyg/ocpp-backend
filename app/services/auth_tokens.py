# app/services/auth_tokens.py
"""
Saját, aláírt intent-token (v1i) – külső könyvtár nélkül: HMAC-SHA256-tal aláírt, állapotmentes
token ("v1i.<b64url(intent:<id>)>.<exp>.<sig>"), a vendég-töltés nyugta-/leállítási linkjének
bizonyítéka. (A régi e-mail-kódos belépés v1 e-mail-tokenje megszűnt; a "v1." előtagú tokent
semmi nem fogadja el.)

A titok forrása AUTH_SECRET. ÁTMENETILEG, amíg az élesben nincs beállítva, a STRIPE_WEBHOOK_SECRET-re
esik vissza (induláskor figyelmeztetés a naplóban) – az AUTH_SECRET beállítása után a
visszaesés törlendő: egy titok egy célra.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from typing import Optional


def secret_is_fallback() -> bool:
    """True, ha nincs AUTH_SECRET, és az intent-tokent a Stripe webhook-titok írja alá."""
    return not os.environ.get("AUTH_SECRET")


def _secret() -> bytes:
    s = os.environ.get("AUTH_SECRET") or os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not s:
        raise RuntimeError("Missing AUTH_SECRET (and STRIPE_WEBHOOK_SECRET fallback)")
    return s.encode("utf-8")


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# A típus-prefix az aláírt payload része: más prefixű (pl. a megszűnt "v1" e-mail-) token
# nem címkézhető át intent-tokenné az aláírás elrontása nélkül.
_KIND_INTENT = "v1i"   # alany: "intent:<id>"


def _issue(subject: str, ttl_s: int) -> str:
    exp = int(time.time()) + int(ttl_s)
    payload = f"{_KIND_INTENT}.{_b64u(subject.encode('utf-8'))}.{exp}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify(token: Optional[str]) -> Optional[str]:
    """Visszaadja az alanyt, ha a token intent-típusú, érvényes és nem járt le."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != _KIND_INTENT:
        return None
    payload = ".".join(parts[:3])
    sig = parts[3]
    expected = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        exp = int(parts[2])
    except ValueError:
        return None
    if exp < int(time.time()):
        return None
    try:
        return _b64u_decode(parts[1]).decode("utf-8")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Intent-token: a vendég (regisztráció nélküli) töltés "birtoklási" bizonyítéka
# ---------------------------------------------------------------------------
# A POST /api/intents/ adja ki, a Stripe success_url-ben és a "töltés elindult"
# e-mail linkjében utazik, és a POST /api/sessions/{id}/stop ezzel ellenőrzi, hogy
# tényleg az állítja le a töltést, aki fizetett érte. Nem kell hozzá bejelentkezés.
INTENT_TOKEN_TTL_S = 7 * 24 * 60 * 60


def _intent_subject(intent_id: int) -> str:
    return f"intent:{int(intent_id)}"


def issue_intent_token(intent_id: int) -> str:
    return _issue(_intent_subject(intent_id), INTENT_TOKEN_TTL_S)


def verify_intent_token(token: Optional[str], intent_id: Optional[int]) -> bool:
    """True, ha a token intent-típusú, érvényes és pont ehhez az intenthez tartozik."""
    if not token or intent_id is None:
        return False
    return _verify(token) == _intent_subject(intent_id)
