"""Biztonsági keményítés (2026-10-14).

- publikus töltőlista: csak a térképhez szükséges mezők, pszeudonim public_id; régi QR-ok
  (sorszámos id / ocpp_id) feloldása; publikálatlan (belső teszt) töltő sehol;
- OCPP Basic Auth (Security Profile 2) – off / log / enforce, duplikált kapcsolat szabály;
- admin kulcs-generálás (nem küld a töltőre);
- API-dokumentáció kikapcsolva; rate limit; stop_reason; Stripe Checkout lejárat (B1).
"""
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ["ADMIN_PASSWORD"] = "test-admin-pw"
os.environ["AUTH_SECRET"] = "test-auth-secret"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
os.environ["PUBLIC_BASE_URL"] = "https://ev.test"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

import app.api.routers.intents as _intents_mod
import app.api.routers.payments_stripe as _stripe_mod
import app.ocpp.handlers.transactions as _tx_mod
import app.ocpp.registry as registry
from app.core import rate_limit
from app.db.models import ChargePoint, ChargeSession, ChargingIntent, Location
from app.ocpp import auth as ocpp_auth
from app.ocpp.time_utils import utcnow
from app.ocpp.ws import handle_ocpp
from app.services.auth_tokens import issue_intent_token
from tests.conftest import TestSession

_stripe_mod.AsyncSessionLocal = TestSession
_tx_mod.AsyncSessionLocal = TestSession

ADMIN_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:test-admin-pw").decode()}
BILLING = {
    "billing_type": "personal", "billing_name": "Teszt Elek", "billing_street": "Fő u. 1.",
    "billing_zip": "1051", "billing_city": "Budapest", "billing_country": "HU",
}
PUBLIC_FIELDS = {
    "id", "status", "location_name", "address_text", "latitude", "longitude",
    "connector_type", "max_power_kw", "price_huf_per_kwh", "min_charge_huf", "shared_supply",
}


async def _cp(ocpp_id, published=True, load_group=None, key_hash=None):
    async with TestSession() as s:
        loc = Location(name="Teszt helyszín", address_text="1051 Budapest, Tér 1.",
                       latitude=47.5, longitude=19.0)
        s.add(loc)
        await s.flush()
        cp = ChargePoint(ocpp_id=ocpp_id, location_id=loc.id, connector_type="Type 2",
                         max_power_kw=22.0, status="available", last_seen_at=utcnow(),
                         is_published=published, model="VOLTIE PRO", vendor="VOLTIE",
                         load_group=load_group, load_group_max_a=32 if load_group else None,
                         ocpp_auth_key_hash=key_hash)
        s.add(cp)
        await s.commit()
        return cp.id, cp.public_id


# ── Publikus töltőlista ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_public_list_only_map_fields(client):
    await _cp("PUB-1", load_group="grp")
    r = await client.get("/api/charge-points/")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == PUBLIC_FIELDS
    raw = r.text
    for leak in ("PUB-1", "ocpp_id", "last_seen", "VOLTIE", "grp", "load_group", "current_limit"):
        assert leak not in raw, leak
    assert row["shared_supply"] is True


@pytest.mark.asyncio
async def test_internal_unpublished_charger_never_public(client):
    """Belső teszt töltő (publikálatlan): se a listában, se lookuppal, se fizetéssel."""
    await _cp("PUB-OK")
    hid_id, hid_pid = await _cp("BELSO-TESZT-01", published=False)
    r = await client.get("/api/charge-points/")
    assert "BELSO-TESZT-01" not in r.text and hid_pid not in r.text
    for ref in (hid_pid, str(hid_id), "BELSO-TESZT-01"):
        assert (await client.get(f"/api/charge-points/{ref}")).status_code == 404
        r = await client.post("/api/intents/", json={
            "charge_point_id": ref, "email": "a@b.hu", "hold_amount_huf": 5000, **BILLING})
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_lookup_accepts_legacy_qr_refs_but_never_echoes_ocpp_id(client):
    cp_id, pid = await _cp("nadudvar_x")
    for ref in (pid, str(cp_id), "nadudvar_x"):
        r = await client.get(f"/api/charge-points/{ref}")
        assert r.status_code == 200, ref
        assert r.json()["id"] == pid
        assert "nadudvar_x" not in r.text


@pytest.mark.asyncio
async def test_intent_accepts_public_id(client, monkeypatch):
    captured = {}

    def _create(**params):
        captured.update(params)
        return {"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}

    monkeypatch.setattr(_intents_mod.stripe.checkout.Session, "create", _create)
    _, pid = await _cp("INT-1")
    before = int(time.time())
    r = await client.post("/api/intents/", json={
        "charge_point_id": pid, "email": "u@example.hu", "hold_amount_huf": 5000, **BILLING})
    assert r.status_code == 200, r.text
    # B1: a Checkout a Stripe minimumán (30 perc) belül lejár, nem 24 óra múlva
    exp = captured["expires_at"]
    assert before + 30 * 60 <= exp <= before + 35 * 60


# ── Stripe B1: lejárt intent fizetése → zárolás azonnal feloldva ─────────────

def _signed(payload):
    raw = json.dumps(payload).encode()
    ts = int(time.time())
    sig = hmac.new(b"whsec_test", f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return raw, {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_paid_expired_intent_releases_hold(client, monkeypatch):
    monkeypatch.setattr(_stripe_mod, "utcnow", lambda: datetime.utcnow())
    released = []

    async def _fake_release(intent, reason):
        released.append((intent.id, reason))
        intent.status = "cancelled"
        intent.cancel_reason = reason

    monkeypatch.setattr(_stripe_mod, "_release_hold", _fake_release)
    cp_id, _ = await _cp("EXP-1")
    async with TestSession() as s:
        intent = ChargingIntent(charge_point_id=cp_id, connector_id=1, anonymous_email="x@y.hu",
                                status="pending_payment", hold_amount_huf=5000,
                                expires_at=utcnow() - timedelta(minutes=1))
        s.add(intent)
        await s.commit()
        iid = intent.id
    raw, headers = _signed({"id": "evt_x", "type": "checkout.session.completed", "data": {"object": {
        "id": "cs_x", "payment_status": "unpaid", "payment_intent": "pi_x",
        "metadata": {"intent_id": str(iid)}}}})
    r = await client.post("/api/payments/stripe/webhook", content=raw, headers=headers)
    assert r.status_code == 200
    assert released == [(iid, "intent_expired")]
    async with TestSession() as s:
        it = (await s.execute(select(ChargingIntent).where(ChargingIntent.id == iid))).scalar_one()
        assert it.status == "expired"
        assert it.stripe_payment_intent_id == "pi_x"
        assert (await s.execute(select(ChargeSession))).scalars().all() == []

    # a PaySuccess 410-et kap (nem pollozik a végtelenségig)
    r = await client.get(f"/api/sessions/by-intent/{iid}", headers={"X-Intent-Token": issue_intent_token(iid)})
    assert r.status_code == 410


# ── stop_reason ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_transaction_stores_reason(monkeypatch):
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(_tx_mod, "send_receipt_email", _noop, raising=False)
    monkeypatch.setattr(_tx_mod, "create_session_invoice", _noop, raising=False)
    cp_id, _ = await _cp("STOP-1")
    async with TestSession() as s:
        cs = ChargeSession(charge_point_id=cp_id, connector_id=1, ocpp_transaction_id="77",
                           started_at=utcnow(), meter_start_wh=0)
        s.add(cs)
        await s.commit()
        sid = cs.id
    await _tx_mod.stop_transaction("STOP-1", {"transactionId": 77, "meterStop": 1000,
                                              "timestamp": "2026-10-14T10:00:00Z", "reason": "EVDisconnected"})
    async with TestSession() as s:
        cs = (await s.execute(select(ChargeSession).where(ChargeSession.id == sid))).scalar_one()
        assert cs.finished_at is not None
        assert cs.stop_reason == "EVDisconnected"


# ── API-dokumentáció ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_docs_not_public(client):
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/"):
        assert (await client.get(path)).status_code == 404, path


# ── Rate limit ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_per_cf_ip(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    rate_limit.STORE.clear()
    rule = next(r for r in rate_limit.RULES if r.name == "session_view")
    small = rate_limit.Rule(rule.name, rule.method, rule.pattern, 3, 60)
    monkeypatch.setattr(rate_limit, "RULES", tuple(small if r.name == rule.name else r for r in rate_limit.RULES))
    a = {"CF-Connecting-IP": "203.0.113.1", "X-Forwarded-For": "1.1.1.1"}
    for _ in range(3):
        assert (await client.get("/api/sessions/1", headers=a)).status_code == 403
    r = await client.get("/api/sessions/1", headers=a)
    assert r.status_code == 429 and r.headers.get("retry-after")
    # hamisított X-Forwarded-For nem segít; másik (valódi) kliens-IP nem érintett
    assert (await client.get("/api/sessions/1", headers={**a, "X-Forwarded-For": "9.9.9.9"})).status_code == 429
    assert (await client.get("/api/sessions/1", headers={"CF-Connecting-IP": "203.0.113.2"})).status_code == 403
    # nem korlátozott útvonal (pl. Stripe webhook) nem számít
    rate_limit.STORE.clear()


# ── OCPP hitelesítés ─────────────────────────────────────────────────────────

def test_key_hash_and_both_password_forms():
    key = ocpp_auth.generate_key()
    assert len(key) == 40 and int(key, 16) >= 0
    h = ocpp_auth.hash_key(key)
    assert key not in h
    assert ocpp_auth.verify_password(key.encode(), h)
    assert ocpp_auth.verify_password(key.upper().encode(), h)
    assert ocpp_auth.verify_password(bytes.fromhex(key), h)       # "binary" értelmezés
    assert not ocpp_auth.verify_password(b"rossz", h)
    assert not ocpp_auth.verify_password(key.encode(), None)


def _basic(user, pwd):
    return "Basic " + base64.b64encode(f"{user}:{pwd}".encode()).decode()


def test_evaluate_modes():
    key = ocpp_auth.generate_key()
    h = ocpp_auth.hash_key(key)
    ok = _basic("CP1", key)
    ev = ocpp_auth.evaluate
    # log: mindenkit beenged, de az eredményt megmondja
    assert ev(cp_id="CP1", cp_known=True, key_hash=h, authorization=ok, scheme="wss", mode="log").result == "ok"
    d = ev(cp_id="CP1", cp_known=True, key_hash=h, authorization=None, scheme="ws", mode="log")
    assert d.accept and d.result == "missing"
    d = ev(cp_id="CP1", cp_known=True, key_hash=h, authorization=_basic("CP2", key), scheme="wss", mode="log")
    assert d.accept and d.result == "wrong"
    assert ev(cp_id="X", cp_known=False, key_hash=None, authorization=None, scheme="ws", mode="log").accept
    # enforce
    assert ev(cp_id="CP1", cp_known=True, key_hash=h, authorization=ok, scheme="wss", mode="enforce").accept
    d = ev(cp_id="CP1", cp_known=True, key_hash=h, authorization=ok, scheme="ws", mode="enforce")
    assert not d.accept and d.reason == "tls_required"
    d = ev(cp_id="CP1", cp_known=True, key_hash=h, authorization=_basic("CP1", "x" * 40), scheme="wss", mode="enforce")
    assert not d.accept and d.http_status == 401
    d = ev(cp_id="CP1", cp_known=True, key_hash=None, authorization=None, scheme="wss", mode="enforce")
    assert not d.accept and d.result == "no_key"
    assert not ev(cp_id="X", cp_known=False, key_hash=None, authorization=None, scheme="wss", mode="enforce").accept
    assert not ev(cp_id=None, cp_known=False, key_hash=None, authorization=None, scheme="wss", mode="enforce").accept


def test_transport_scheme_from_proxy_headers():
    ts = ocpp_auth.transport_scheme
    assert ts({"cf-visitor": '{"scheme":"https"}'}, "ws") == "wss"
    assert ts({"cf-visitor": '{"scheme":"http"}', "x-forwarded-proto": "https"}, "wss") == "ws"
    assert ts({"x-forwarded-proto": "https"}, "ws") == "wss"
    assert ts({}, "ws") == "ws"


class FakeWS:
    """Minimális Starlette-WebSocket utánzat a kézfogás-logika teszteléséhez."""

    def __init__(self, headers=None, scheme="ws", messages=()):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.url = type("U", (), {"scheme": scheme})()
        self.accepted = False
        self.denied = None
        self.closed = None
        self.sent = []
        self._messages = list(messages)

    async def accept(self, subprotocol=None):
        self.accepted = True

    async def send_denial_response(self, response):
        self.denied = response.status_code

    async def close(self, code=1000, reason=None):
        self.closed = code

    async def receive_text(self):
        if self._messages:
            return self._messages.pop(0)
        raise WebSocketDisconnect()

    async def send_text(self, text):
        self.sent.append(text)


async def _auth_state(ocpp_id):
    async with TestSession() as s:
        return (await s.execute(
            select(ChargePoint.ocpp_auth_last_result, ChargePoint.ocpp_last_scheme)
            .where(ChargePoint.ocpp_id == ocpp_id))).one()


@pytest.mark.asyncio
async def test_ws_log_mode_accepts_and_records(monkeypatch):
    monkeypatch.setenv("OCPP_AUTH_MODE", "log")
    key = ocpp_auth.generate_key()
    await _cp("WS-1", key_hash=ocpp_auth.hash_key(key))
    await _cp("WS-2")

    ws = FakeWS(scheme="ws")                      # nincs jelszó, titkosítatlan
    await handle_ocpp(ws, "WS-1")
    assert ws.accepted and ws.denied is None
    assert tuple(await _auth_state("WS-1")) == ("missing", "ws")

    ws = FakeWS({"Authorization": _basic("WS-1", key), "CF-Visitor": '{"scheme":"https"}'})
    await handle_ocpp(ws, "WS-1")
    assert ws.accepted
    assert tuple(await _auth_state("WS-1")) == ("ok", "wss")

    ws = FakeWS()
    await handle_ocpp(ws, "WS-2")
    assert ws.accepted
    assert tuple(await _auth_state("WS-2")) == ("no_key", "ws")

    ws = FakeWS()                                  # ismeretlen: log módban beengedjük (onboarding)
    await handle_ocpp(ws, "WS-UNKNOWN")
    assert ws.accepted


@pytest.mark.asyncio
async def test_ws_enforce_mode_rejects(monkeypatch):
    monkeypatch.setenv("OCPP_AUTH_MODE", "enforce")
    key = ocpp_auth.generate_key()
    await _cp("WS-E", key_hash=ocpp_auth.hash_key(key))
    tls = {"CF-Visitor": '{"scheme":"https"}'}

    for headers, status in (
        (tls, 401),                                                   # nincs jelszó
        ({**tls, "Authorization": _basic("WS-E", "0" * 40)}, 401),    # rossz jelszó
        ({"Authorization": _basic("WS-E", key)}, 403),                # jó jelszó, de ws://
    ):
        ws = FakeWS(headers)
        await handle_ocpp(ws, "WS-E")
        assert not ws.accepted and ws.denied == status, headers

    ws = FakeWS(tls)
    await handle_ocpp(ws, "NINCS-ILYEN")
    assert not ws.accepted and ws.denied == 403

    ws = FakeWS({**tls, "Authorization": _basic("WS-E", key)})
    await handle_ocpp(ws, "WS-E")
    assert ws.accepted and ws.denied is None


@pytest.mark.asyncio
async def test_ws_off_mode_ignores_credentials(monkeypatch):
    monkeypatch.setenv("OCPP_AUTH_MODE", "off")
    await _cp("WS-OFF", key_hash=ocpp_auth.hash_key(ocpp_auth.generate_key()))
    ws = FakeWS()
    await handle_ocpp(ws, "WS-OFF")
    assert ws.accepted


@pytest.mark.asyncio
async def test_duplicate_connection_policy():
    real, impostor, newer = FakeWS(), FakeWS(), FakeWS()
    try:
        # hitelesített kapcsolat él → nem hitelesített új kapcsolat elutasítva
        ok, old = await registry.admit_ws("DUP-1", real, authenticated=True)
        assert ok and old is None
        ok, old = await registry.admit_ws("DUP-1", impostor, authenticated=False)
        assert not ok
        assert await registry.get_ws("DUP-1") is real
        # hitelesített új kapcsolat (pl. újracsatlakozás) nyer, a régit a hívó lezárja
        ok, old = await registry.admit_ws("DUP-1", newer, authenticated=True)
        assert ok and old is real
        # hitelesítés nélküli állapotban (bevezetés előtt) a legújabb nyer – mint eddig
        a, b = FakeWS(), FakeWS()
        assert (await registry.admit_ws("DUP-2", a, False))[0]
        ok, old = await registry.admit_ws("DUP-2", b, False)
        assert ok and old is a
    finally:
        for cp in ("DUP-1", "DUP-2"):
            ws = await registry.get_ws(cp)
            if ws is not None:
                await registry.unregister_ws_if_same(cp, ws)


@pytest.mark.asyncio
async def test_ws_duplicate_unauthenticated_refused_by_handler(monkeypatch):
    monkeypatch.setenv("OCPP_AUTH_MODE", "log")
    real = FakeWS()
    await registry.admit_ws("DUP-H", real, authenticated=True)
    try:
        await _cp("DUP-H", key_hash=ocpp_auth.hash_key(ocpp_auth.generate_key()))
        ws = FakeWS()
        await handle_ocpp(ws, "DUP-H")
        assert not ws.accepted and ws.denied == 409
        assert await registry.get_ws("DUP-H") is real
    finally:
        await registry.unregister_ws_if_same("DUP-H", real)


# ── Admin kulcs-generálás ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_generate_key_does_not_send(client, monkeypatch):
    sent = []

    async def _fake_change(*a, **k):
        sent.append(a)
        return {"status": "Accepted"}

    monkeypatch.setattr(registry, "change_configuration", _fake_change)
    cp_id, _ = await _cp("KEY-1")
    assert (await client.post(f"/api/admin/charge-points/{cp_id}/ocpp-auth-key")).status_code == 401

    r = await client.post(f"/api/admin/charge-points/{cp_id}/ocpp-auth-key", headers=ADMIN_AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    key = body["key"]
    assert body["sent_to_charger"] is False
    assert body["change_configuration"] == {"key": "AuthorizationKey", "value": key}
    assert body["basic_auth_username"] == "KEY-1"
    assert sent == []
    async with TestSession() as s:
        cp = (await s.execute(select(ChargePoint).where(ChargePoint.id == cp_id))).scalar_one()
        assert cp.ocpp_auth_key_hash and key not in cp.ocpp_auth_key_hash
        assert ocpp_auth.verify_password(key.encode(), cp.ocpp_auth_key_hash)

    # apply alapból tiltva (éles töltő konfigurációja csak jóváhagyással)
    monkeypatch.delenv("OCPP_AUTH_APPLY_ENABLED", raising=False)
    r = await client.post(f"/api/admin/charge-points/{cp_id}/ocpp-auth-key/apply",
                          json={"key": key}, headers=ADMIN_AUTH)
    assert r.status_code == 403 and sent == []

    # engedélyezve: rossz kulccsal nem küld, jóval igen
    monkeypatch.setenv("OCPP_AUTH_APPLY_ENABLED", "true")
    r = await client.post(f"/api/admin/charge-points/{cp_id}/ocpp-auth-key/apply",
                          json={"key": "0" * 40}, headers=ADMIN_AUTH)
    assert r.status_code == 409 and sent == []
    r = await client.post(f"/api/admin/charge-points/{cp_id}/ocpp-auth-key/apply",
                          json={"key": key}, headers=ADMIN_AUTH)
    assert r.status_code == 200 and sent == [("KEY-1", "AuthorizationKey", key)]

    # admin lista mutatja az állapotot, a kulcsot nem
    r = await client.get("/api/admin/charge-points", headers=ADMIN_AUTH)
    row = [c for c in r.json() if c["ocpp_id"] == "KEY-1"][0]
    assert row["ocpp_auth"]["key_set"] is True and key not in r.text

    r = await client.delete(f"/api/admin/charge-points/{cp_id}/ocpp-auth-key", headers=ADMIN_AUTH)
    assert r.status_code == 200


# ── Töltő-konfiguráció (áramkorlát) – admin, allowlist ───────────────────────

@pytest.mark.asyncio
async def test_admin_change_config_current_limit(client, monkeypatch):
    state = {"CurrentLimitHardware": "32", "CurrentLimitUser": "17", "CurrentLimitDefault": "17"}
    changes = []

    async def _fake_call(cp, action, payload, timeout_s=12.0):
        assert action == "GetConfiguration"
        return {"configurationKey": [{"key": k, "readonly": False, "value": state[k]}
                                     for k in payload["key"] if k in state]}

    async def _fake_change(cp, key, value):
        changes.append((cp, key, value))
        state[key] = value
        return {"status": "Accepted"}

    monkeypatch.setattr(registry, "send_call_and_wait", _fake_call)
    monkeypatch.setattr(registry, "change_configuration", _fake_change)
    cp_id, _ = await _cp("CFG-1")
    url = f"/api/admin/charge-points/{cp_id}/config"

    assert (await client.post(url, json={"key": "CurrentLimitUser", "value": "32"})).status_code == 401
    # nem engedélyezett kulcsok (pl. a hitelesítési bevezetés kulcsai) → 400, nincs küldés
    for k in ("AuthorizationKey", "OCPPBackendJSONURL", "AllowOfflineTxForUnknownId", "CurrentDynamic"):
        r = await client.post(url, json={"key": k, "value": "1"}, headers=ADMIN_AUTH)
        assert r.status_code == 400, k
    for v in ("5", "33", "abc", "-1", "16.5"):
        r = await client.post(url, json={"key": "CurrentLimitUser", "value": v}, headers=ADMIN_AUTH)
        assert r.status_code == 422, v
    assert changes == []

    r = await client.post(url, json={"key": "CurrentLimitUser", "value": "32"}, headers=ADMIN_AUTH)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["old"] == "17" and b["new"] == "32" and b["status"] == "Accepted" and b["hardware_limit"] == 32
    assert changes == [("CFG-1", "CurrentLimitUser", "32")]

    # ismeretlen hardveres plafon → nem írunk
    state.pop("CurrentLimitHardware")
    r = await client.post(url, json={"key": "CurrentLimitDefault", "value": "32"}, headers=ADMIN_AUTH)
    assert r.status_code == 409 and len(changes) == 1
