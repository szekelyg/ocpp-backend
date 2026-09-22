"""Egységes Energiafelhő-fiók (Keycloak) – JWT-ellenőrzés és a /api/me/* végpontok.

- A JWKS-t nem a hálózatról töltjük: saját RSA-kulcspárral írjuk alá a tokeneket, és a
  keycloak modul httpx-kliensét egy hamis klienssel helyettesítjük, ami a hozzá tartozó
  JWKS-t adja vissza (így a JWKS-parszolás és a cache is tesztelve van).
- Fail-closed esetek: lejárt, rossz iss, rossz aud/azp, `none`/HS256 alg, rossz kulcs,
  ismeretlen kid, ID-token, megerősítetlen e-mail, kikapcsolt Keycloak.
- /api/me/sessions kizárólag a bejelentkezett e-mail töltéseit adja (idegen → nem látszik,
  idegen számla → 404), e-mail-tokennel és Keycloak-tokennel egyaránt.
"""
import base64
import os
import time
import uuid
from datetime import timedelta

os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ["ADMIN_PASSWORD"] = "test-admin-pw"
os.environ["AUTH_SECRET"] = "test-auth-secret"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
os.environ["PUBLIC_BASE_URL"] = "https://ev.test"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

import app.api.routers.intents as _intents_mod
import app.api.routers.sessions as _sessions_mod
import app.services.keycloak as kc
from app.db.models import ChargePoint, ChargeSession, ChargingIntent, Location, User
from app.ocpp.time_utils import utcnow
from app.services.auth_tokens import issue_token
from tests.conftest import TestSession

ISSUER = "https://id.test/realms/ugyfelek"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"


# ── kulcsok + hamis JWKS-szerver ─────────────────────────────────────────────

def _b64u(n: int, length: int) -> str:
    return base64.urlsafe_b64encode(n.to_bytes(length, "big")).decode().rstrip("=")


def _rsa_pair(kid: str):
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = priv.public_key().public_numbers()
    jwk = {"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256",
           "n": _b64u(pub.n, 256), "e": _b64u(pub.e, 3)}
    return priv, jwk


KEY_A, JWK_A = _rsa_pair("kid-a")
KEY_B, JWK_B = _rsa_pair("kid-b")   # kulcsforgatás / idegen kulcs


class _FakeResponse:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class _FakeAsyncClient:
    """A keycloak modul httpx.AsyncClient-je helyett: JWKS + discovery a memóriából."""
    jwks_keys = [JWK_A]
    calls: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        _FakeAsyncClient.calls.append(url)
        if url == JWKS_URL:
            return _FakeResponse({"keys": list(_FakeAsyncClient.jwks_keys)})
        if url == DISCOVERY_URL:
            return _FakeResponse({
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                "end_session_endpoint": f"{ISSUER}/protocol/openid-connect/logout",
            })
        return _FakeResponse({}, 404)


@pytest.fixture(autouse=True)
def keycloak_env(monkeypatch):
    monkeypatch.setenv("KEYCLOAK_ISSUER", ISSUER)
    monkeypatch.setenv("KEYCLOAK_AUDIENCE", "ev")
    monkeypatch.setenv("KEYCLOAK_ALLOWED_AZP", "portal")
    monkeypatch.delenv("KEYCLOAK_JWKS_URL", raising=False)
    monkeypatch.setattr(kc.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.jwks_keys = [JWK_A]
    _FakeAsyncClient.calls = []
    kc.reset_cache()
    yield
    kc.reset_cache()


def make_token(*, key=KEY_A, kid="kid-a", alg="RS256", email="ugyfel@example.hu",
               verified=True, sub=None, aud="ev", azp="ev", exp_in=300, iss=ISSUER,
               typ="Bearer", extra=None, drop=()):
    now = int(time.time())
    claims = {
        "iss": iss, "sub": sub or str(uuid.uuid4()), "iat": now, "exp": now + exp_in,
        "azp": azp, "typ": typ, "email": email, "email_verified": verified,
        "name": "Teszt Ügyfél", "preferred_username": email,
    }
    if aud is not None:
        claims["aud"] = aud
    claims.update(extra or {})
    for k in drop:
        claims.pop(k, None)
    headers = {"kid": kid} if kid else {}
    if alg == "none":
        return jwt.encode(claims, key=None, algorithm="none", headers=headers)
    if alg.startswith("HS"):
        return jwt.encode(claims, key=key, algorithm=alg, headers=headers)
    return jwt.encode(claims, key=key, algorithm=alg, headers=headers)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── seed ────────────────────────────────────────────────────────────────────

async def _seed_cp(ocpp_id="CP-KC", with_location=True):
    async with TestSession() as s:
        loc_id = None
        if with_location:
            loc = Location(name="Teszt Parkoló", address_text="1111 Budapest, Teszt u. 1.")
            s.add(loc)
            await s.flush()
            loc_id = loc.id
        cp = ChargePoint(ocpp_id=ocpp_id, status="available", last_seen_at=utcnow(),
                         is_published=True, location_id=loc_id)
        s.add(cp)
        await s.commit()
        return cp.id


async def _seed_session(cp_id, email, *, kwh=None, huf=None, invoice=None, finished=True,
                        tx="TX", with_intent=True):
    async with TestSession() as s:
        intent_id = None
        if with_intent:
            intent = ChargingIntent(
                charge_point_id=cp_id, connector_id=1, anonymous_email=email, status="paid",
                hold_amount_huf=5000, expires_at=utcnow() + timedelta(minutes=15),
            )
            s.add(intent)
            await s.flush()
            intent_id = intent.id
        started = utcnow() - timedelta(hours=1)
        cs = ChargeSession(
            charge_point_id=cp_id, connector_id=1, ocpp_transaction_id=f"{tx}-{uuid.uuid4().hex[:6]}",
            started_at=started, finished_at=(utcnow() if finished else None),
            anonymous_email=email, intent_id=intent_id, energy_kwh=kwh, cost_huf=huf,
            invoice_number=invoice,
        )
        s.add(cs)
        await s.commit()
        return cs.id


async def _users():
    async with TestSession() as s:
        return (await s.execute(select(User))).scalars().all()


# ── JWT-ellenőrzés ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_valid_keycloak_token_links_user(client):
    tok = make_token(email="Ugyfel@Example.hu", sub="sub-1")
    r = await client.get("/api/me", headers=bearer(tok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "ugyfel@example.hu"          # kisbetűsítve
    assert body["auth_source"] == "keycloak"
    assert body["keycloak_linked"] is True
    assert body["name"] == "Teszt Ügyfél"
    users = await _users()
    assert len(users) == 1 and users[0].email == "ugyfel@example.hu" and users[0].keycloak_sub == "sub-1"

    # a JWKS egyszer töltődött be, a második kérés a cache-ből megy
    n = _FakeAsyncClient.calls.count(JWKS_URL)
    assert (await client.get("/api/me", headers=bearer(tok))).status_code == 200
    assert _FakeAsyncClient.calls.count(JWKS_URL) == n


@pytest.mark.asyncio
async def test_existing_email_user_gets_linked_and_profile_returned(client):
    async with TestSession() as s:
        s.add(User(email="regi@example.hu", billing_name="Régi Réka", billing_city="Pécs"))
        await s.commit()
    r = await client.get("/api/me", headers=bearer(make_token(email="regi@example.hu", sub="sub-regi")))
    assert r.status_code == 200
    assert r.json()["keycloak_linked"] is True
    assert r.json()["profile"]["billing_name"] == "Régi Réka"
    users = await _users()
    assert len(users) == 1 and users[0].keycloak_sub == "sub-regi"


@pytest.mark.asyncio
async def test_portal_token_accepted_via_azp_without_aud(client):
    """A portál (my.energiafelho.hu) tokenjében nincs `ev` az aud-ban, csak azp=portal."""
    r = await client.get("/api/me", headers=bearer(make_token(aud=None, azp="portal")))
    assert r.status_code == 200, r.text
    r = await client.get("/api/me", headers=bearer(make_token(aud="account", azp="portal")))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_own_spa_client_token_accepted_without_audience_mapper(client, monkeypatch):
    """Az `ev` kliens tokenjében a Keycloak alapból csak `account` aud van; azp=ev elég."""
    monkeypatch.setenv("KEYCLOAK_ALLOWED_AZP", "")
    r = await client.get("/api/me", headers=bearer(make_token(aud="account", azp="ev")))
    assert r.status_code == 200, r.text
    # aud-listában az ev (audience-mapperrel) szintén jó
    r = await client.get("/api/me", headers=bearer(make_token(aud=["account", "ev"], azp="portal")))
    assert r.status_code == 200
    # de a portál azp-je engedélyezés nélkül nem
    r = await client.get("/api/me", headers=bearer(make_token(aud="account", azp="portal")))
    assert r.status_code == 401 and r.json()["detail"] == "keycloak_invalid_audience"


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs, reason", [
    (dict(exp_in=-120), "token_expired"),
    (dict(iss="https://id.test/realms/masik"), "invalid_issuer"),
    (dict(aud="account", azp="idegen"), "invalid_audience"),
    (dict(aud=None, azp="ev-nem"), "invalid_audience"),
    (dict(typ="ID"), "not_access_token"),
    (dict(typ="Refresh"), "not_access_token"),
    (dict(kid=None), "missing_kid"),
    (dict(kid="kid-nincs"), "unknown_kid"),
    (dict(key=KEY_B, kid="kid-a"), "invalid_token"),          # idegen kulccsal aláírva
    (dict(drop=("exp",)), "invalid_token"),                   # exp kötelező
    (dict(drop=("email",)), "email_claim_missing"),
])
async def test_rejected_tokens(client, kwargs, reason):
    r = await client.get("/api/me", headers=bearer(make_token(**kwargs)))
    assert r.status_code == 401, r.text
    assert r.json()["detail"] == f"keycloak_{reason}"
    assert await _users() == []


@pytest.mark.asyncio
async def test_none_and_hs_algorithms_rejected(client):
    r = await client.get("/api/me", headers=bearer(make_token(alg="none")))
    assert r.status_code == 401 and r.json()["detail"] == "keycloak_alg_not_allowed"
    # "HS256 a nyilvános kulccsal mint titokkal" trükk (a PyJWT encode maga sem engedi, ezért
    # kézzel rakjuk össze): az alg-fehérlista miatt már a fejlécnél elbukik
    import hashlib, hmac, json
    from cryptography.hazmat.primitives import serialization
    pub_pem = KEY_A.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)

    def _seg(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).decode().rstrip("=")

    now = int(time.time())
    payload = {"iss": ISSUER, "sub": "x", "iat": now, "exp": now + 300, "aud": "ev", "azp": "ev",
               "typ": "Bearer", "email": "hacker@example.hu", "email_verified": True}
    signing = _seg(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "kid-a"}).encode()) + "." + \
        _seg(json.dumps(payload).encode())
    forged = signing + "." + _seg(hmac.new(pub_pem, signing.encode(), hashlib.sha256).digest())
    r = await client.get("/api/me", headers=bearer(forged))
    assert r.status_code == 401 and r.json()["detail"] == "keycloak_alg_not_allowed"
    assert await _users() == []


@pytest.mark.asyncio
async def test_garbage_bearer_is_401(client):
    for t in ("nem.jwt", "a.b.c", "v1.x.y.z", "Bearer"):
        r = await client.get("/api/me", headers=bearer(t))
        assert r.status_code == 401, t
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/me/sessions")).status_code == 401


@pytest.mark.asyncio
async def test_unverified_email_is_403_and_not_linked(client):
    tok = make_token(email="nemigazolt@example.hu", verified=False, sub="sub-x")
    r = await client.get("/api/me", headers=bearer(tok))
    assert r.status_code == 403
    assert r.json()["detail"] == "keycloak_email_not_verified"
    assert (await client.get("/api/me/sessions", headers=bearer(tok))).status_code == 403
    assert await _users() == []


@pytest.mark.asyncio
async def test_keycloak_disabled_is_fail_closed(client, monkeypatch):
    monkeypatch.delenv("KEYCLOAK_ISSUER")
    kc.reset_cache()
    r = await client.get("/api/me", headers=bearer(make_token()))
    assert r.status_code == 401 and r.json()["detail"] == "keycloak_keycloak_disabled"
    # az e-mail-token ettől függetlenül működik
    r = await client.get("/api/me", headers=bearer(issue_token("otp@example.hu")))
    assert r.status_code == 200 and r.json()["auth_source"] == "email_token"
    assert r.json()["keycloak_linked"] is False
    # és a config végpont szerint nincs Keycloak
    r = await client.get("/api/auth/keycloak/config")
    assert r.status_code == 200 and r.json() == {"enabled": False}


@pytest.mark.asyncio
async def test_key_rotation_refetches_jwks_once(client, monkeypatch):
    monkeypatch.setattr(kc, "JWKS_REFETCH_MIN_INTERVAL_S", 0)
    assert (await client.get("/api/me", headers=bearer(make_token()))).status_code == 200
    # új kulcs a Keycloakban → a következő token ezzel jön; egy újratöltés után elfogadjuk
    _FakeAsyncClient.jwks_keys = [JWK_A, JWK_B]
    r = await client.get("/api/me", headers=bearer(make_token(key=KEY_B, kid="kid-b")))
    assert r.status_code == 200, r.text
    assert _FakeAsyncClient.calls.count(JWKS_URL) == 2


@pytest.mark.asyncio
async def test_unknown_kid_refetch_is_throttled(client):
    """Hamis kid-del nem lehet percenként többször a Keycloakhoz szaladtatni a backendet."""
    assert (await client.get("/api/me", headers=bearer(make_token()))).status_code == 200
    n = _FakeAsyncClient.calls.count(JWKS_URL)
    for _ in range(3):
        r = await client.get("/api/me", headers=bearer(make_token(kid="kid-hamis")))
        assert r.status_code == 401
    assert _FakeAsyncClient.calls.count(JWKS_URL) == n


@pytest.mark.asyncio
async def test_keycloak_config_endpoint(client):
    r = await client.get("/api/auth/keycloak/config")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True and body["client_id"] == "ev" and body["issuer"] == ISSUER
    assert body["authorization_endpoint"].endswith("/protocol/openid-connect/auth")
    assert body["token_endpoint"].endswith("/protocol/openid-connect/token")
    assert body["end_session_endpoint"].endswith("/protocol/openid-connect/logout")


# ── /api/me/sessions – csak a saját töltések ────────────────────────────────

@pytest.mark.asyncio
async def test_my_sessions_only_own_email(client):
    cp_id = await _seed_cp()
    mine1 = await _seed_session(cp_id, "Sajat@Example.hu", kwh=10.5, huf=1785, invoice="EV-2026-1")
    mine2 = await _seed_session(cp_id, "sajat@example.hu", kwh=2.0, huf=500, finished=False)
    other = await _seed_session(cp_id, "masik@example.hu", kwh=99.0, huf=99999, invoice="EV-2026-9")

    r = await client.get("/api/me/sessions", headers=bearer(make_token(email="sajat@example.hu")))
    assert r.status_code == 200, r.text
    body = r.json()
    ids = [s["id"] for s in body["sessions"]]
    assert set(ids) == {mine1, mine2} and other not in ids
    assert body["total"] == 2
    assert body["total_kwh"] == 12.5
    assert body["total_huf"] == 2285
    assert body["currency"] == "HUF"

    by_id = {s["id"]: s for s in body["sessions"]}
    assert by_id[mine1]["charge_point"] == {"id": cp_id, "ocpp_id": "CP-KC", "name": "Teszt Parkoló",
                                            "address": "1111 Budapest, Teszt u. 1."}
    assert by_id[mine1]["status"] == "finished" and by_id[mine1]["invoice_number"] == "EV-2026-1"
    assert by_id[mine1]["invoice_url"] == f"/api/me/sessions/{mine1}/invoice"
    assert by_id[mine2]["status"] == "active" and by_id[mine2]["invoice_url"] is None
    assert by_id[mine1]["cost_huf"] == 1785 and by_id[mine1]["energy_kwh"] == 10.5

    # idegen fiók: semmi (nem 403 – egyszerűen nincs mit mutatni)
    r = await client.get("/api/me/sessions", headers=bearer(make_token(email="senki@example.hu")))
    assert r.status_code == 200
    assert r.json()["sessions"] == [] and r.json()["total"] == 0 and r.json()["total_huf"] == 0


@pytest.mark.asyncio
async def test_my_sessions_with_email_token_and_pagination(client):
    cp_id = await _seed_cp(with_location=False)
    for i in range(5):
        await _seed_session(cp_id, "otp@example.hu", kwh=1.0, huf=170, tx=f"T{i}")
    await _seed_session(cp_id, "masik@example.hu", kwh=1.0, huf=170)

    h = bearer(issue_token("otp@example.hu"))
    r = await client.get("/api/me/sessions?limit=2&offset=0", headers=h)
    assert r.status_code == 200
    b = r.json()
    assert len(b["sessions"]) == 2 and b["total"] == 5 and b["total_kwh"] == 5.0 and b["total_huf"] == 850
    assert b["sessions"][0]["charge_point"]["name"] == "CP-KC"   # nincs location → ocpp_id
    r2 = await client.get("/api/me/sessions?limit=2&offset=4", headers=h)
    assert len(r2.json()["sessions"]) == 1
    assert (await client.get("/api/me/sessions?limit=0", headers=h)).status_code == 422


@pytest.mark.asyncio
async def test_invoice_pdf_only_for_own_session(client, monkeypatch):
    import app.services.invoice as _inv
    calls = []

    async def _fake_pdf(invoice_number):
        calls.append(invoice_number)
        return b"%PDF-1.4 teszt"

    monkeypatch.setattr(_inv, "fetch_invoice_pdf", _fake_pdf)
    cp_id = await _seed_cp()
    mine = await _seed_session(cp_id, "sajat@example.hu", invoice="EV-2026-1")
    no_inv = await _seed_session(cp_id, "sajat@example.hu")
    other = await _seed_session(cp_id, "masik@example.hu", invoice="EV-2026-9")

    h = bearer(make_token(email="sajat@example.hu"))
    r = await client.get(f"/api/me/sessions/{mine}/invoice", headers=h)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF") and "szamla_EV-2026-1.pdf" in r.headers["content-disposition"]
    assert (await client.get(f"/api/me/sessions/{other}/invoice", headers=h)).status_code == 404
    assert (await client.get(f"/api/me/sessions/{no_inv}/invoice", headers=h)).status_code == 404
    assert (await client.get(f"/api/me/sessions/{mine}/invoice")).status_code == 401
    assert calls == ["EV-2026-1"], "idegen / számlátlan sessionre nem kérdezzük a Számlázz.hu-t"


# ── CORS: csak /api/me/*, csak a portál originje ─────────────────────────────

@pytest.mark.asyncio
async def test_cors_only_on_me_routes_for_portal_origin(client):
    preflight = {"Origin": "https://my.energiafelho.hu", "Access-Control-Request-Method": "GET",
                 "Access-Control-Request-Headers": "authorization"}
    r = await client.options("/api/me/sessions", headers=preflight)
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == "https://my.energiafelho.hu"
    assert "authorization" in r.headers.get("access-control-allow-headers", "").lower()
    assert r.headers.get("access-control-allow-credentials") is None   # no-cookie

    r = await client.get("/api/me", headers={**bearer(make_token()), "Origin": "https://my.energiafelho.hu"})
    assert r.status_code == 200 and r.headers.get("access-control-allow-origin") == "https://my.energiafelho.hu"

    # idegen origin: nincs CORS-fejléc
    r = await client.get("/api/me", headers={**bearer(make_token()), "Origin": "https://gonosz.example"})
    assert r.headers.get("access-control-allow-origin") is None
    # más útvonal: nincs CORS a portálnak sem
    r = await client.get("/api/charge-points/", headers={"Origin": "https://my.energiafelho.hu"})
    assert r.headers.get("access-control-allow-origin") is None


# ── Meglévő folyamatok Keycloak-belépéssel ───────────────────────────────────

@pytest.mark.asyncio
async def test_public_stop_with_keycloak_token_of_owner(client, monkeypatch):
    calls = []

    async def _fake_stop(cp_id, transaction_id):
        calls.append(cp_id)
        return {"status": "Accepted"}

    monkeypatch.setattr(_sessions_mod, "remote_stop_transaction", _fake_stop)
    cp_id = await _seed_cp()
    sid = await _seed_session(cp_id, "Tulaj@Example.hu", finished=False)

    r = await client.post(f"/api/sessions/{sid}/stop", headers=bearer(make_token(email="masik@example.hu")))
    assert r.status_code == 403 and calls == []
    r = await client.post(f"/api/sessions/{sid}/stop", headers=bearer(make_token(email="tulaj@example.hu", verified=False)))
    assert r.status_code == 403 and calls == []
    r = await client.post(f"/api/sessions/{sid}/stop", headers=bearer(make_token(email="tulaj@example.hu")))
    assert r.status_code == 200, r.text
    assert calls == ["CP-KC"]


@pytest.fixture
def fake_checkout(monkeypatch):
    captured = {}

    def _create(**params):
        captured.update(params)
        return {"id": "cs_test_kc", "url": "https://checkout.stripe.com/c/pay/cs_test_kc"}

    monkeypatch.setattr(_intents_mod.stripe.checkout.Session, "create", _create)
    return captured


@pytest.mark.asyncio
async def test_intent_uses_account_email_and_saved_billing(client, fake_checkout):
    """SSO a töltőnél: a fiók e-mailje számít, a számlázási adatok a mentett profilból jönnek."""
    cp_id = await _seed_cp()
    async with TestSession() as s:
        s.add(User(email="fiok@example.hu", billing_type="business", billing_name="Fiók Ferenc",
                   billing_street="Fő tér 1.", billing_zip="7621", billing_city="Pécs",
                   billing_country="HU", billing_company="Fiók Kft.", billing_tax_number="11111111-2-02"))
        await s.commit()

    tok = make_token(email="fiok@example.hu")
    r = await client.post("/api/intents/", headers=bearer(tok), json={
        "charge_point_id": cp_id, "connector_id": 1, "hold_amount_huf": 5000,
        "email": "hamis@example.hu",           # figyelmen kívül marad
        "billing_type": "business",
    })
    assert r.status_code == 200, r.text
    assert fake_checkout["customer_email"] == "fiok@example.hu"
    async with TestSession() as s:
        intent = (await s.execute(select(ChargingIntent))).scalar_one()
        assert intent.anonymous_email == "fiok@example.hu"
        assert intent.billing_name == "Fiók Ferenc" and intent.billing_company == "Fiók Kft."
        assert intent.billing_tax_number == "11111111-2-02" and intent.billing_city == "Pécs"

    # a body-beli mező felülírja a profilt (a felhasználó átírta az űrlapon)
    r = await client.post("/api/intents/", headers=bearer(tok), json={
        "charge_point_id": cp_id, "billing_type": "personal", "billing_name": "Más Név",
    })
    assert r.status_code == 200, r.text
    async with TestSession() as s:
        intents = (await s.execute(select(ChargingIntent).order_by(ChargingIntent.id))).scalars().all()
        assert intents[-1].billing_name == "Más Név" and intents[-1].billing_company is None


@pytest.mark.asyncio
async def test_intent_guest_still_needs_email_and_billing(client, fake_checkout):
    cp_id = await _seed_cp()
    billing = {"billing_name": "Vendég Vilma", "billing_street": "Utca 1.", "billing_zip": "1000",
               "billing_city": "Budapest", "billing_country": "HU"}
    r = await client.post("/api/intents/", json={"charge_point_id": cp_id, **billing})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "email_required"
    r = await client.post("/api/intents/", json={"charge_point_id": cp_id, "email": "v@example.hu"})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "billing_missing"
    r = await client.post("/api/intents/", json={"charge_point_id": cp_id, "email": "V@Example.hu", **billing})
    assert r.status_code == 200, r.text
    assert fake_checkout["customer_email"] == "v@example.hu"
    # bejelentkezve, de mentett profil nélkül és üres űrlappal: 422 (nem találunk ki adatot)
    r = await client.post("/api/intents/", headers=bearer(make_token(email="uj@example.hu")),
                          json={"charge_point_id": cp_id})
    assert r.status_code == 422 and r.json()["detail"]["error"] == "billing_missing"


@pytest.mark.asyncio
async def test_intent_with_invalid_token_is_401_not_guest(client, fake_checkout):
    """Fail-closed: hibás/lejárt Bearer nem esik vissza csendben vendég-módba."""
    cp_id = await _seed_cp()
    r = await client.post("/api/intents/", headers=bearer(make_token(exp_in=-100)), json={
        "charge_point_id": cp_id, "email": "v@example.hu", "billing_name": "V", "billing_street": "U 1",
        "billing_zip": "1000", "billing_city": "B", "billing_country": "HU",
    })
    assert r.status_code == 401
    assert fake_checkout == {}
