# app/services/auth_tokens.py
"""
Jelszó nélküli bejelentkezés segédfüggvényei – külső könyvtár nélkül.

- Bejelentkezési kód (OTP): 6 jegyű, sózott SHA-256 hash-t tárolunk (a nyerset soha).
- Session token: HMAC-SHA256-tal aláírt, állapotmentes token ("v1.<b64url(email)>.<exp>.<sig>").

A titok forrása AUTH_SECRET; ha nincs beállítva, a már meglévő STRIPE_WEBHOOK_SECRET-re
esik vissza, hogy külön konfiguráció nélkül is deploy-olható legyen.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

# Kód: 6 számjegy, 10 perc érvényesség, max 5 próbálkozás
CODE_TTL_S = 10 * 60
CODE_MAX_ATTEMPTS = 5
# Új kód kérése között minimum ennyi teljen el (anti-spam)
CODE_RESEND_COOLDOWN_S = 45
# Session token élettartama: 30 nap
TOKEN_TTL_S = 30 * 24 * 60 * 60


def _secret() -> bytes:
    s = os.environ.get("AUTH_SECRET") or os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not s:
        raise RuntimeError("Missing AUTH_SECRET (and STRIPE_WEBHOOK_SECRET fallback)")
    return s.encode("utf-8")


# ---------------------------------------------------------------------------
# OTP kód
# ---------------------------------------------------------------------------

def generate_code() -> str:
    """Kriptográfiailag biztonságos 6 jegyű kód (vezető nullákkal)."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_code(email: str, code: str) -> str:
    """Email-hez sózott SHA-256 hex – így ugyanaz a kód más emailhez más hash."""
    msg = f"{email.strip().lower()}:{code.strip()}".encode("utf-8")
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def verify_code_hash(email: str, code: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_code(email, code), stored_hash)


# ---------------------------------------------------------------------------
# Session token (állapotmentes, aláírt)
# ---------------------------------------------------------------------------

def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# Token-típusok: a verzió-/típus-prefix az aláírt payload része, így egy e-mail-token
# nem címkézhető át intent-tokenné (és fordítva) az aláírás elrontása nélkül.
_KIND_EMAIL = "v1"     # alany: e-mail-cím
_KIND_INTENT = "v1i"   # alany: "intent:<id>"


def _issue(kind: str, subject: str, ttl_s: int) -> str:
    subject = subject.strip().lower()
    exp = int(time.time()) + int(ttl_s)
    payload = f"{kind}.{_b64u(subject.encode('utf-8'))}.{exp}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify(kind: str, token: Optional[str]) -> Optional[str]:
    """Visszaadja az alanyt, ha a token az adott típusú, érvényes és nem járt le."""
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != kind:
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


def issue_token(email: str, ttl_s: int = TOKEN_TTL_S) -> str:
    return _issue(_KIND_EMAIL, email, ttl_s)


def verify_token(token: str) -> Optional[str]:
    """Visszaadja az email-t, ha az e-mail-token érvényes és nem járt le; különben None.

    Csak e-mail-típusú (v1) tokent fogad el; az intent-token (v1i) itt None.
    """
    email = _verify(_KIND_EMAIL, token)
    return email if email and "@" in email else None


# ---------------------------------------------------------------------------
# Intent-token: a vendég (regisztráció nélküli) töltés "birtoklási" bizonyítéka
# ---------------------------------------------------------------------------
# Ugyanaz az aláírt token-formátum, de külön típus-prefixszel (v1i) és "intent:<id>" alannyal.
# A POST /api/intents/ adja ki, a Stripe success_url-ben és a "töltés elindult"
# e-mail linkjében utazik, és a POST /api/sessions/{id}/stop ezzel ellenőrzi, hogy
# tényleg az állítja le a töltést, aki fizetett érte. Nem kell hozzá bejelentkezés.
INTENT_TOKEN_TTL_S = 7 * 24 * 60 * 60


def _intent_subject(intent_id: int) -> str:
    return f"intent:{int(intent_id)}"


def issue_intent_token(intent_id: int) -> str:
    return _issue(_KIND_INTENT, _intent_subject(intent_id), INTENT_TOKEN_TTL_S)


def verify_intent_token(token: Optional[str], intent_id: Optional[int]) -> bool:
    """True, ha a token intent-típusú, érvényes és pont ehhez az intenthez tartozik.

    E-mail-token (v1) itt sosem érvényes, akkor sem, ha az alanya "intent:<id>" lenne.
    """
    if not token or intent_id is None:
        return False
    return _verify(_KIND_INTENT, token) == _intent_subject(intent_id)
