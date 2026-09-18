"""Session- és intent-végpontok hozzáférés-védelme.

- GET /api/sessions/ (lista) és /active/by-charge-point csak admin.
- POST /api/sessions/{id}/stop csak az indítónak: intent-tokennel (a fizetéskor kiadott,
  aláírt token) vagy a saját e-mailjéhez tartozó Bearer-tokennel. Regisztráció nem kell.
- GET /api/sessions/{id} és /by-intent/{id} publikus marad (a vendég-folyamat pollozza).
- POST /api/intents/: nem ír a users táblába; a success_url-ben intent-token utazik;
  e-mail-enkénti throttle. A profil a fizetett webhookban mentődik.
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
os.environ["STRIPE_SECRET_KEY"] = "sk_test_dummy"  # a Stripe-hívást a tesztek stubolják

import pytest
from sqlalchemy import select

import app.api.routers.intents as _intents_mod
import app.api.routers.payments_stripe as _stripe_mod
import app.api.routers.sessions as _sessions_mod
from app.db.models import ChargePoint, ChargeSession, ChargingIntent, User
from app.ocpp.time_utils import utcnow
from app.services.auth_tokens import issue_intent_token, issue_token, verify_intent_token
from tests.conftest import TestSession

# A webhook saját DB-sessiont nyit import-időben kötött sessionmakerrel → teszt DB-re.
_stripe_mod.AsyncSessionLocal = TestSession

ADMIN_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:test-admin-pw").decode()}

BILLING = {
    "billing_type": "personal", "billing_name": "Teszt Elek", "billing_street": "Fő u. 1.",
    "billing_zip": "1051", "billing_city": "Budapest", "billing_country": "HU",
}


async def _seed_cp(ocpp_id="CP-AUTH", status="available"):
    async with TestSession() as s:
        cp = ChargePoint(ocpp_id=ocpp_id, status=status, last_seen_at=utcnow(),
                         is_published=True, connector_type="Type 2", max_power_kw=22.0)
        s.add(cp)
        await s.commit()
        return cp.id


async def _seed_session(cp_id, email="vendeg@example.hu", with_intent=True, tx="TX-1"):
    """Fizetett intent + hozzá tartozó aktív session (mint a webhook után)."""
    async with TestSession() as s:
        intent_id = None
        if with_intent:
            intent = ChargingIntent(
                charge_point_id=cp_id, connector_id=1, anonymous_email=email,
                status="paid", hold_amount_huf=5000, expires_at=utcnow() + timedelta(minutes=15),
            )
            s.add(intent)
            await s.flush()
            intent_id = intent.id
        cs = ChargeSession(
            charge_point_id=cp_id, connector_id=1, ocpp_transaction_id=tx,
            started_at=utcnow(), anonymous_email=email, intent_id=intent_id,
        )
        s.add(cs)
        await s.commit()
        return cs.id, intent_id


@pytest.fixture
def stop_accepted(monkeypatch):
    """Az OCPP RemoteStop-ot nem a töltő, hanem egy stub válaszolja meg."""
    calls = []

    async def _fake_stop(cp_id, transaction_id):
        calls.append((cp_id, transaction_id))
        return {"status": "Accepted"}

    monkeypatch.setattr(_sessions_mod, "remote_stop_transaction", _fake_stop)
    return calls


# ── Lista: csak admin ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_list_requires_admin(client):
    cp_id = await _seed_cp()
    await _seed_session(cp_id)

    assert (await client.get("/api/sessions/")).status_code == 401
    assert (await client.get(f"/api/sessions/active/by-charge-point/{cp_id}")).status_code == 401

    r = await client.get("/api/sessions/", headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert (await client.get(f"/api/sessions/active/by-charge-point/{cp_id}",
                             headers=ADMIN_AUTH)).status_code == 200


@pytest.mark.asyncio
async def test_single_session_stays_public(client):
    """A vendég-oldal (ChargingPage, PaySuccess) token nélkül pollozza a saját sessionjét."""
    cp_id = await _seed_cp()
    sid, intent_id = await _seed_session(cp_id)
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 200
    assert (await client.get(f"/api/sessions/by-intent/{intent_id}")).status_code == 200


# ── Stop: csak az indító ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_public_stop_rejects_without_proof(client, stop_accepted):
    cp_id = await _seed_cp()
    sid, intent_id = await _seed_session(cp_id)
    _, other_intent = await _seed_session(cp_id, email="masik@example.hu", tx="TX-2")

    # Semmi (a régi, nyitott viselkedés)
    r = await client.post(f"/api/sessions/{sid}/stop")
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "stop_not_authorized"

    # Üres body, hibás / más intenthez tartozó / rossz kulcsú token
    assert (await client.post(f"/api/sessions/{sid}/stop", json={})).status_code == 403
    assert (await client.post(f"/api/sessions/{sid}/stop",
                              json={"token": "v1.x.y.z"})).status_code == 403
    assert (await client.post(f"/api/sessions/{sid}/stop",
                              json={"token": issue_intent_token(other_intent)})).status_code == 403
    # Egy e-mail-token nem intent-token, még ha a "subject" egyezne is
    assert (await client.post(f"/api/sessions/{sid}/stop",
                              json={"token": issue_token(f"intent:{intent_id}"[::-1])})).status_code == 403

    # Más e-mail Bearer-tokenje
    assert (await client.post(
        f"/api/sessions/{sid}/stop",
        headers={"Authorization": f"Bearer {issue_token('masik@example.hu')}"},
    )).status_code == 403

    assert stop_accepted == [], "jogosulatlan kérésre nem mehet RemoteStop a töltőnek"


@pytest.mark.asyncio
async def test_public_stop_with_intent_token(client, stop_accepted):
    cp_id = await _seed_cp()
    sid, intent_id = await _seed_session(cp_id)

    r = await client.post(f"/api/sessions/{sid}/stop", json={"token": issue_intent_token(intent_id)})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert stop_accepted == [("CP-AUTH", "TX-1")]


@pytest.mark.asyncio
async def test_public_stop_with_own_email_token(client, stop_accepted):
    """Tartalék: e-mail-kódos belépés után a saját e-mailhez tartozó töltés leállítható."""
    cp_id = await _seed_cp()
    sid, _ = await _seed_session(cp_id, email="Vendeg@Example.hu")

    r = await client.post(
        f"/api/sessions/{sid}/stop",
        headers={"Authorization": f"Bearer {issue_token('vendeg@example.hu')}"},
    )
    assert r.status_code == 200, r.text
    assert len(stop_accepted) == 1


@pytest.mark.asyncio
async def test_public_stop_session_without_intent_is_not_stoppable_by_guests(client, stop_accepted):
    """Admin/OCPI indítású (intent nélküli) sessiont vendég nem állíthat le."""
    cp_id = await _seed_cp()
    sid, _ = await _seed_session(cp_id, with_intent=False)
    assert (await client.post(f"/api/sessions/{sid}/stop",
                              json={"token": issue_intent_token(1)})).status_code == 403
    assert stop_accepted == []


@pytest.mark.asyncio
async def test_admin_stop_still_works(client, stop_accepted):
    cp_id = await _seed_cp()
    sid, _ = await _seed_session(cp_id)
    assert (await client.post("/api/sessions/stop", json={"session_id": sid})).status_code == 401
    r = await client.post("/api/sessions/stop", json={"session_id": sid}, headers=ADMIN_AUTH)
    assert r.status_code == 200, r.text


# ── Intents: users-írás, token, throttle ─────────────────────────────────────

@pytest.fixture
def fake_checkout(monkeypatch):
    captured = {}

    def _create(**params):
        captured.update(params)
        return {"id": "cs_test_1", "url": "https://checkout.stripe.com/c/pay/cs_test_1"}

    monkeypatch.setattr(_intents_mod.stripe.checkout.Session, "create", _create)
    return captured


@pytest.mark.asyncio
async def test_create_intent_issues_token_and_does_not_write_users(client, fake_checkout):
    cp_id = await _seed_cp()
    r = await client.post("/api/intents/", json={
        "charge_point_id": cp_id, "connector_id": 1, "email": "uj@example.hu",
        "hold_amount_huf": 5000, "save_profile": True, **BILLING,
    })
    assert r.status_code == 200, r.text
    intent_id = r.json()["intent_id"]

    # success_url-ben ott az intent-token, és az pont ehhez az intenthez érvényes
    url = fake_checkout["success_url"]
    assert url.startswith(f"https://ev.test/pay/success?intent_id={intent_id}&t=")
    token = url.split("&t=", 1)[1]
    assert verify_intent_token(token, intent_id)
    assert not verify_intent_token(token, intent_id + 1)

    # a save_profile jelző a Stripe metadatában utazik, a users tábla üres marad
    assert fake_checkout["metadata"]["save_profile"] == "1"
    async with TestSession() as s:
        assert (await s.execute(select(User))).scalars().all() == []


@pytest.mark.asyncio
async def test_create_intent_rate_limited_per_email(client, fake_checkout):
    from app.api.routers.intents import INTENT_RATE_MAX_PER_EMAIL

    cp_id = await _seed_cp()
    async with TestSession() as s:
        for _ in range(INTENT_RATE_MAX_PER_EMAIL):
            s.add(ChargingIntent(
                charge_point_id=cp_id, connector_id=1, anonymous_email="spam@example.hu",
                status="pending_payment", hold_amount_huf=5000,
                expires_at=utcnow() + timedelta(minutes=15),
            ))
        await s.commit()

    body = {"charge_point_id": cp_id, "connector_id": 1, "email": "spam@example.hu",
            "hold_amount_huf": 5000, **BILLING}
    r = await client.post("/api/intents/", json=body)
    assert r.status_code == 429
    assert r.json()["detail"]["error"] == "too_many_intents"

    # más e-mail-címet nem érint
    r = await client.post("/api/intents/", json={**body, "email": "rendes@example.hu"})
    assert r.status_code == 200, r.text


def _signed_webhook(payload: dict) -> tuple[bytes, dict]:
    raw = json.dumps(payload).encode()
    ts = int(time.time())
    sig = hmac.new(b"whsec_test", f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    return raw, {"Stripe-Signature": f"t={ts},v1={sig}", "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_webhook_saves_profile_only_when_flagged(client, monkeypatch):
    # SQLite naiv datetime-ot ad vissza (Postgres tz-aware-t): a lejárat-összehasonlításhoz
    # a webhook "most"-ját is naivra vesszük, különben TypeError – tesztkörnyezeti artefaktum.
    monkeypatch.setattr(_stripe_mod, "utcnow", lambda: datetime.utcnow())
    cp_id = await _seed_cp()
    async with TestSession() as s:
        intent = ChargingIntent(
            charge_point_id=cp_id, connector_id=1, anonymous_email="Fizeto@Example.hu",
            status="pending_payment", hold_amount_huf=5000,
            expires_at=utcnow() + timedelta(minutes=15),
            billing_type="business", billing_name="Fizető Ferenc", billing_street="Út 2.",
            billing_zip="1111", billing_city="Buda", billing_country="HU",
            billing_company="Fizető Kft.", billing_tax_number="12345678-2-42",
        )
        s.add(intent)
        await s.commit()
        intent_id = intent.id

    def _event(save_profile: str):
        return {
            "id": "evt_1", "type": "checkout.session.completed",
            "data": {"object": {
                "id": "cs_test_1", "payment_status": "unpaid", "payment_intent": "pi_1",
                "metadata": {"intent_id": str(intent_id), "save_profile": save_profile},
            }},
        }

    raw, headers = _signed_webhook(_event("0"))
    assert (await client.post("/api/payments/stripe/webhook", content=raw, headers=headers)).status_code == 200
    async with TestSession() as s:
        assert (await s.execute(select(User))).scalars().all() == []

    raw, headers = _signed_webhook(_event("1"))
    assert (await client.post("/api/payments/stripe/webhook", content=raw, headers=headers)).status_code == 200
    async with TestSession() as s:
        users = (await s.execute(select(User))).scalars().all()
        assert len(users) == 1
        assert users[0].email == "fizeto@example.hu"
        assert users[0].billing_company == "Fizető Kft."
        sessions = (await s.execute(select(ChargeSession))).scalars().all()
        assert len(sessions) == 1, "a webhook ismétlése idempotens marad"
