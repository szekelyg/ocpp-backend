# app/ocpp/auth.py
"""OCPP 1.6 Security Profile 2: TLS + HTTP Basic Auth töltőnként.

- Felhasználónév = a töltő azonosítója (chargePointId, nálunk az URL-ben lévő ocpp_id).
- Jelszó = a töltő AuthorizationKey-e. A kulcsot a backend generálja (32 hex karakter = 16 bájt),
  a DB-ben csak a PBKDF2-SHA256 hash-e van (charge_points.ocpp_auth_key_hash).
- Mód: OCPP_AUTH_MODE = off | log | enforce (alap: log)
    off     – semmit nem ellenőrzünk (a régi viselkedés), csak a sémát naplózzuk;
    log     – minden kapcsolatot beengedünk, de töltőnként rögzítjük és naplózzuk az eredményt
              (ok / missing / wrong / no_key); ismeretlen ocpp_id-t is beengedünk (a
              BootNotification publikálatlanul felveszi, „konfigurálásra vár");
    enforce – csak TLS-en (wss) érkező, helyes Basic Auth-tal azonosított, ismert töltő
              kapcsolódhat; minden más 401/403.

A 1.6-os security whitepaper az AuthorizationKey-t hex-reprezentációban adja meg; a töltők egy
része a hex szöveget küldi jelszóként, más része a dekódolt 20 bájtot. Mindkettőt elfogadjuk
(a nyers bájtokat hex-szé alakítva hasonlítjuk) – így a Voltie bármelyik értelmezése működik.

Részletek, bevezetési terv: docs/OCPP-HITELESITES.md
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Literal, Optional

logger = logging.getLogger("ocpp.auth")

AuthMode = Literal["off", "log", "enforce"]
AuthResult = Literal["ok", "missing", "wrong", "no_key", "unknown_cp"]

_PBKDF2_ITER = 120_000
KEY_BYTES = 16  # 32 hex karakter – a Voltie PRO (fw 1.3.54-3.75) a 40 hex karakterest Rejected-del
#                  elutasítja, a 32-est elfogadja (2026-10-14, nadudvar_spar_2); a whitepaper 16..20 bájtján belül


def auth_mode() -> AuthMode:
    v = (os.environ.get("OCPP_AUTH_MODE") or "log").strip().lower()
    if v not in ("off", "log", "enforce"):
        logger.error("Ismeretlen OCPP_AUTH_MODE=%r – 'log' módban futunk", v)
        return "log"
    return v  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Kulcs generálás / hash / ellenőrzés
# ---------------------------------------------------------------------------

def generate_key() -> str:
    """Új AuthorizationKey: 32 kisbetűs hex karakter (16 véletlen bájt)."""
    return secrets.token_hex(KEY_BYTES)


def hash_key(key: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", key.encode("utf-8"), salt, _PBKDF2_ITER)
    return "pbkdf2_sha256${}${}${}".format(
        _PBKDF2_ITER,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(dk).decode("ascii"),
    )


def _check_one(candidate: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
        dk = hashlib.pbkdf2_hmac("sha256", candidate.encode("utf-8"), salt, int(iters))
    except Exception:
        return False
    return hmac.compare_digest(dk, expected)


def verify_password(password: bytes, stored_hash: Optional[str]) -> bool:
    """A kapott jelszó (nyers bájtok) egyezik-e a tárolt kulccsal.

    Elfogadott alakok: a hex szöveg maga (kis- vagy nagybetűvel), vagy a hex-ből dekódolt
    nyers bájtok (a whitepaper „binary" értelmezése).
    """
    if not stored_hash or not password:
        return False
    candidates = []
    try:
        txt = password.decode("utf-8")
        candidates.append(txt)
        if txt.lower() != txt:
            candidates.append(txt.lower())
    except UnicodeDecodeError:
        pass
    if len(password) in (16, 20):  # nyers kulcsbájtok → hex
        candidates.append(binascii.hexlify(password).decode("ascii"))
    return any(_check_one(c, stored_hash) for c in candidates)


# ---------------------------------------------------------------------------
# Kapcsolódás-kori kiértékelés
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BasicCreds:
    username: str
    password: bytes


def parse_basic(authorization: Optional[str]) -> Optional[BasicCreds]:
    if not authorization:
        return None
    scheme, _, value = authorization.strip().partition(" ")
    if scheme.lower() != "basic" or not value.strip():
        return None
    try:
        raw = base64.b64decode(value.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    user, sep, pwd = raw.partition(b":")
    if not sep:
        return None
    try:
        username = user.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return BasicCreds(username=username, password=pwd)


def transport_scheme(headers, url_scheme: str) -> str:
    """'wss' ha a töltő TLS-en jött (a Cloudflare edge-ig), különben 'ws'.

    Élesben a Cloudflare tunnel adja a TLS-t; a cloudflared a backend felé sima HTTP-n
    proxyz, de jelzi az eredeti sémát (CF-Visitor, X-Forwarded-Proto). A backend csak a
    tunnelen (és a szerver localhostján) érhető el, így ezek a fejlécek megbízhatók.
    """
    cf_visitor = headers.get("cf-visitor")
    if cf_visitor:
        try:
            sch = str(json.loads(cf_visitor).get("scheme", "")).lower()
            if sch:
                return "wss" if sch in ("https", "wss") else "ws"
        except Exception:
            pass
    xfp = (headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if xfp:
        return "wss" if xfp in ("https", "wss") else "ws"
    return "wss" if url_scheme in ("wss", "https") else "ws"


@dataclass(frozen=True)
class AuthDecision:
    result: AuthResult
    scheme: str
    accept: bool
    http_status: int = 0       # elutasításkor: 401 (hitelesítés), 403 (egyéb)
    reason: str = ""

    @property
    def authenticated(self) -> bool:
        return self.result == "ok"


def evaluate(
    *,
    cp_id: Optional[str],
    cp_known: bool,
    key_hash: Optional[str],
    authorization: Optional[str],
    scheme: str,
    mode: Optional[AuthMode] = None,
    cp_published: bool = True,
) -> AuthDecision:
    """Eldönti, beengedjük-e a kapcsolatot (a DB-írás/naplózás a hívó dolga)."""
    mode = mode or auth_mode()

    if not cp_known:
        result: AuthResult = "unknown_cp"
    elif not key_hash:
        result = "no_key"
    else:
        creds = parse_basic(authorization)
        if creds is None:
            result = "missing"
        elif creds.username != cp_id or not verify_password(creds.password, key_hash):
            result = "wrong"
        else:
            result = "ok"

    if mode != "enforce":
        return AuthDecision(result=result, scheme=scheme, accept=True)

    # enforce
    if not cp_id:
        return AuthDecision(result=result, scheme=scheme, accept=False, http_status=403, reason="unknown_cp")
    if scheme != "wss":
        return AuthDecision(result=result, scheme=scheme, accept=False, http_status=403, reason="tls_required")
    if not cp_known or (not key_hash and not cp_published):
        # Új töltő felvétele: az új (ismeretlen) vagy még publikálatlan, kulcs nélküli töltő jelszó
        # nélkül is kapcsolódhat – fizetés nem indítható rá, a térképen és az OCPI-ban nem látszik.
        # A jelszót publikáláskor kapja meg (admin PUT is_published=true), onnantól kötelező.
        return AuthDecision(result=result, scheme=scheme, accept=True)
    if result != "ok":
        return AuthDecision(result=result, scheme=scheme, accept=False, http_status=401, reason=result)
    return AuthDecision(result=result, scheme=scheme, accept=True)


def change_configuration_payload(key: str) -> dict:
    """A töltőnek küldendő OCPP 1.6 ChangeConfiguration payload (NEM küldjük el automatikusan)."""
    return {"key": "AuthorizationKey", "value": key}
