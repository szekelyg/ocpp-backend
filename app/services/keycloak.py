# app/services/keycloak.py
"""
Keycloak (egységes Energiafelhő-fiók) access token ellenőrzése.

A SPA (Authorization Code + PKCE, public kliens `ev`) és a portál (my.energiafelho.hu)
Bearer access tokent küld; itt a realm JWKS-ével ellenőrizzük. Fail-closed: ha a
KEYCLOAK_ISSUER nincs beállítva, minden JWT-nek kinéző token érvénytelen.

Env:
  KEYCLOAK_ISSUER       pl. https://id.energiafelho.hu/realms/ugyfelek  (kötelező a bekapcsoláshoz)
  KEYCLOAK_AUDIENCE     az `aud`-ban elvárt kliens, alap: ev
  KEYCLOAK_ALLOWED_AZP  vesszővel elválasztott kliens-lista, amelyek tokenje `aud` nélkül is jó
                        (azp = a tokent kérő kliens), pl. "portal"; a saját `ev` kliens mindig jó
  KEYCLOAK_JWKS_URL     opcionális; alap: {issuer}/protocol/openid-connect/certs
  KEYCLOAK_JWKS_TTL_S   JWKS cache élettartam (alap 3600)

Elvek (a korábbi biztonsági felülvizsgálatból):
  - alg csak RS*/ES* (a `none` és a HS* – a nyilvános kulccsal "aláírt" token – tiltva),
  - iss pontos egyezés, exp kötelező, aud VAGY azp egyezés kötelező,
  - JWKS cache-elve, ismeretlen `kid`-re (kulcsforgatás) egyszeri újratöltés, de
    legfeljebb percenként (különben egy hamis kid-del DoS-olható lenne a Keycloak),
  - csak access token (Keycloak `typ: Bearer`); ID/refresh token nem fogadható el.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger("keycloak")

ALLOWED_ALGS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")
# Órák eltérése miatti tűrés az exp/nbf/iat ellenőrzésénél
LEEWAY_S = 30
# Ismeretlen kid miatti JWKS-újratöltések közötti minimum
JWKS_REFETCH_MIN_INTERVAL_S = 60
JWKS_HTTP_TIMEOUT_S = 5.0


class KeycloakAuthError(Exception):
    """A token nem fogadható el. A `reason` rövid, gépi kód (a 401 detail-jébe kerül)."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason if not detail else f"{reason}: {detail}")
        self.reason = reason


@dataclass(frozen=True)
class KeycloakIdentity:
    sub: str
    email: Optional[str]           # kisbetűsítve
    email_verified: bool
    name: Optional[str]
    azp: Optional[str]
    claims: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def realm_roles(self) -> frozenset[str]:
        """A token `realm_access.roles` listája (a Keycloak alap `roles` client scope adja)."""
        ra = self.claims.get("realm_access")
        roles = ra.get("roles") if isinstance(ra, dict) else None
        if not isinstance(roles, (list, tuple)):
            return frozenset()
        return frozenset(r for r in roles if isinstance(r, str))


# ---------------------------------------------------------------------------
# Konfiguráció (env – futásidőben olvasva, hogy a tesztek is át tudják állítani)
# ---------------------------------------------------------------------------

def issuer() -> Optional[str]:
    v = (os.environ.get("KEYCLOAK_ISSUER") or "").strip().rstrip("/")
    return v or None


def enabled() -> bool:
    return issuer() is not None


def audience() -> str:
    return (os.environ.get("KEYCLOAK_AUDIENCE") or "ev").strip()


def allowed_azp() -> frozenset[str]:
    raw = os.environ.get("KEYCLOAK_ALLOWED_AZP") or ""
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def jwks_url() -> Optional[str]:
    explicit = (os.environ.get("KEYCLOAK_JWKS_URL") or "").strip()
    if explicit:
        return explicit
    iss = issuer()
    return f"{iss}/protocol/openid-connect/certs" if iss else None


def jwks_ttl_s() -> int:
    try:
        return max(60, int(os.environ.get("KEYCLOAK_JWKS_TTL_S") or 3600))
    except ValueError:
        return 3600


# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------

class JWKSCache:
    """kid → nyilvános kulcs (PyJWT PyJWK). Egy példány processzenként, asyncio-lockkal."""

    def __init__(self) -> None:
        self._keys: dict[str, Any] = {}
        self._url: Optional[str] = None
        self._fetched_at: float = 0.0
        self._lock = asyncio.Lock()

    def clear(self) -> None:
        self._keys = {}
        self._url = None
        self._fetched_at = 0.0

    async def _fetch(self, url: str) -> None:
        import jwt  # PyJWT

        async with httpx.AsyncClient(timeout=JWKS_HTTP_TIMEOUT_S) as client:
            resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        keys: dict[str, Any] = {}
        for jwk in data.get("keys", []):
            kid = jwk.get("kid")
            if not kid or jwk.get("use") not in (None, "sig"):
                continue
            if jwk.get("kty") not in ("RSA", "EC"):
                continue
            try:
                keys[kid] = jwt.PyJWK(jwk)
            except Exception as e:  # rossz/ismeretlen kulcs – kihagyjuk, a többi működjön
                logger.warning("JWKS: kulcs kihagyva kid=%s err=%s", kid, e)
        if not keys:
            raise KeycloakAuthError("jwks_empty")
        self._keys = keys
        self._url = url
        self._fetched_at = time.monotonic()
        logger.info("JWKS betöltve url=%s kulcsok=%s", url, ",".join(keys))

    async def get_key(self, kid: str) -> Any:
        url = jwks_url()
        if not url:
            raise KeycloakAuthError("keycloak_disabled")
        async with self._lock:
            now = time.monotonic()
            stale = (
                self._url != url
                or not self._keys
                or now - self._fetched_at > jwks_ttl_s()
            )
            if stale:
                await self._fetch(url)
            key = self._keys.get(kid)
            if key is None and now - self._fetched_at >= JWKS_REFETCH_MIN_INTERVAL_S:
                # kulcsforgatás: egyszer újratöltjük, de nem gyakrabban percenként
                await self._fetch(url)
                key = self._keys.get(kid)
        if key is None:
            raise KeycloakAuthError("unknown_kid")
        return key


_jwks = JWKSCache()


def reset_cache() -> None:
    """Tesztekhez / env-változáshoz."""
    _jwks.clear()


# ---------------------------------------------------------------------------
# Token ellenőrzés
# ---------------------------------------------------------------------------

def looks_like_jwt(token: str) -> bool:
    """Három base64url szegmens – ennyi elég a saját (v1./v1i.) tokenektől való megkülönböztetéshez."""
    parts = token.split(".")
    # az aláírás-szegmens lehet üres (alg=none) – azt is ide irányítjuk, hogy explicit elutasítás legyen
    return len(parts) == 3 and bool(parts[0]) and bool(parts[1]) and not token.startswith(("v1.", "v1i."))


def _aud_ok(claims: dict) -> bool:
    aud = claims.get("aud")
    if isinstance(aud, str):
        aud_set = {aud}
    elif isinstance(aud, (list, tuple)):
        aud_set = {a for a in aud if isinstance(a, str)}
    else:
        aud_set = set()
    if audience() in aud_set:
        return True
    # azp = a tokent kérő kliens. A saját SPA-kliensünk (`ev`) tokenje akkor is jó, ha nincs
    # audience-mapper (a Keycloak alapból csak `account`-ot tesz az aud-ba); más kliens
    # (pl. a portál) csak a KEYCLOAK_ALLOWED_AZP listából.
    azp = claims.get("azp")
    return isinstance(azp, str) and (azp == audience() or azp in allowed_azp())


async def verify_access_token(token: str) -> KeycloakIdentity:
    """Bearer access token → KeycloakIdentity. Bármely hibára KeycloakAuthError."""
    if not enabled():
        raise KeycloakAuthError("keycloak_disabled")
    try:
        import jwt
        from jwt import exceptions as jwt_exc
    except ImportError as e:  # pragma: no cover
        raise KeycloakAuthError("jwt_library_missing", str(e))

    try:
        header = jwt.get_unverified_header(token)
    except jwt_exc.PyJWTError as e:
        raise KeycloakAuthError("malformed_token", str(e))

    alg = header.get("alg")
    if alg not in ALLOWED_ALGS:
        raise KeycloakAuthError("alg_not_allowed", str(alg))
    kid = header.get("kid")
    if not kid or not isinstance(kid, str):
        raise KeycloakAuthError("missing_kid")

    try:
        key = await _jwks.get_key(kid)
    except KeycloakAuthError:
        raise
    except Exception as e:
        logger.warning("JWKS letöltés sikertelen: %s", e)
        raise KeycloakAuthError("jwks_unavailable", str(e))

    try:
        claims = jwt.decode(
            token,
            key=key.key,
            algorithms=[alg],          # csak a fejlécben lévő, már engedélyezett alg
            issuer=issuer(),
            leeway=LEEWAY_S,
            options={
                "require": ["exp", "iat", "iss", "sub"],
                "verify_aud": False,   # aud/azp-t magunk ellenőrizzük (Keycloak: azp + opcionális aud-mapper)
                "verify_signature": True,
            },
        )
    except jwt_exc.ExpiredSignatureError:
        raise KeycloakAuthError("token_expired")
    except jwt_exc.InvalidIssuerError:
        raise KeycloakAuthError("invalid_issuer")
    except jwt_exc.PyJWTError as e:
        raise KeycloakAuthError("invalid_token", str(e))

    if not _aud_ok(claims):
        raise KeycloakAuthError("invalid_audience")

    typ = claims.get("typ")
    if typ is not None and typ != "Bearer":
        raise KeycloakAuthError("not_access_token", str(typ))

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise KeycloakAuthError("missing_sub")

    email = claims.get("email")
    email = email.strip().lower() if isinstance(email, str) and "@" in email else None
    name = _display_name(claims)

    return KeycloakIdentity(
        sub=sub,
        email=email,
        email_verified=bool(claims.get("email_verified", False)),
        name=name if isinstance(name, str) else None,
        azp=claims.get("azp") if isinstance(claims.get("azp"), str) else None,
        claims=claims,
    )


def _display_name(claims: dict[str, Any]) -> str | None:
    """Megjelenítendő név a tokenből — MAGYAR sorrendben.

    Energiafelhő, 2026-09-22: a Keycloak `name` claimje mindig „Keresztnév Vezetéknév"
    (a beépített full-name mapper angol sorrendet ad, realm-szinten nem állítható).
    Ha megvan a `family_name` és a `given_name`, azokból rakjuk össze; a `name`, majd a
    `preferred_username` csak tartalék. Ugyanez a szabály él a portálon
    (customer-auth/name.ts) és az app.energiafelho.hu-n (Accounts.keycloak_nev).
    """
    family = claims.get("family_name")
    given = claims.get("given_name")
    if isinstance(family, str) and isinstance(given, str) and family.strip() and given.strip():
        return f"{family.strip()} {given.strip()}"
    for key in ("name", "preferred_username"):
        v = claims.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


# ---------------------------------------------------------------------------
# OIDC discovery a SPA-nak (GET /api/auth/keycloak/config)
# ---------------------------------------------------------------------------

_discovery_cache: dict[str, Any] = {}
_discovery_fetched_at: float = 0.0
DISCOVERY_TTL_S = 6 * 3600


async def public_config() -> dict:
    """A SPA-nak szükséges, nem titkos OIDC adatok. Nincs Keycloak → {"enabled": False}."""
    global _discovery_cache, _discovery_fetched_at
    iss = issuer()
    if not iss:
        return {"enabled": False}
    client_id = (os.environ.get("KEYCLOAK_SPA_CLIENT_ID") or audience()).strip()
    now = time.monotonic()
    if not _discovery_cache or now - _discovery_fetched_at > DISCOVERY_TTL_S or _discovery_cache.get("issuer") != iss:
        try:
            async with httpx.AsyncClient(timeout=JWKS_HTTP_TIMEOUT_S) as client:
                resp = await client.get(f"{iss}/.well-known/openid-configuration")
            resp.raise_for_status()
            data = resp.json()
            _discovery_cache = {
                "issuer": iss,
                "authorization_endpoint": data.get("authorization_endpoint"),
                "token_endpoint": data.get("token_endpoint"),
                "end_session_endpoint": data.get("end_session_endpoint"),
            }
            _discovery_fetched_at = now
        except Exception as e:
            logger.warning("OIDC discovery sikertelen: %s", e)
            if not _discovery_cache:
                # Tartalék: a Keycloak szabványos útvonalai
                _discovery_cache = {
                    "issuer": iss,
                    "authorization_endpoint": f"{iss}/protocol/openid-connect/auth",
                    "token_endpoint": f"{iss}/protocol/openid-connect/token",
                    "end_session_endpoint": f"{iss}/protocol/openid-connect/logout",
                }
    return {"enabled": True, "client_id": client_id, **_discovery_cache}
