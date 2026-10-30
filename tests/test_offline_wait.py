"""Kifizetett munkamenet, miközben a töltő offline (2026-10-30, Gellért döntése: várjuk meg).

Fizetés → RemoteStart → Accepted → a töltő elveszti a netet → az autót bedugják, a töltő net
nélkül elindítja a töltést → a backend nem látja a StartTransaction-t. Eddig 5 perc után
lezártuk és feloldottuk a zárolást, a visszacsatlakozáskor érkező StartTransaction pedig egy új,
fizetéshez nem kötött munkamenetbe futott (ingyen töltés). Most: offline töltőnél várunk.
"""
import base64
import logging
import os
from datetime import timedelta

os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ["ADMIN_PASSWORD"] = "test-admin-pw"

import pytest
import stripe
from sqlalchemy import select

import app.main as main
import app.ocpp.handlers.pending_start as ps
import app.ocpp.handlers.transactions as _tx_mod
import app.ocpp.registry as reg
import app.services.email as email_mod
from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession

CP = "norg_onk_2"
ADMIN_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:test-admin-pw").decode()}


# ── Segédek ──────────────────────────────────────────────────────────────────

class _World:
    """A töltő kapcsolata (registry), a Stripe-feloldás és az e-mailek rögzítése."""

    def __init__(self, monkeypatch):
        self.online = False
        self.connected_at = None
        self.released = []      # feloldott zárolások (checkout session, munkamenet)
        self.no_start = []      # „nem indult el” e-mailek
        self.captures = []      # Stripe capture (pi, fillér)
        self.cancels = []

        async def get_ws(cp_id):
            return object() if self.online else None

        async def connected_since(cp_id):
            return self.connected_at if self.online else None

        async def release(checkout_session_id, charge_session_id):
            self.released.append((checkout_session_id, charge_session_id))

        async def no_start_email(**kw):
            self.no_start.append(kw)
            return True

        async def no_mail(**kw):
            return True

        async def no_invoice(**kw):
            return None

        def capture(pi_id, amount_to_capture=None):
            self.captures.append((pi_id, amount_to_capture))

        def cancel(pi_id):
            self.cancels.append(pi_id)

        monkeypatch.setattr(reg, "get_ws", get_ws)
        monkeypatch.setattr(reg, "connected_since", connected_since)
        monkeypatch.setattr(main, "_try_stripe_cancel_or_refund", release)
        monkeypatch.setattr(email_mod, "send_no_start_email", no_start_email)
        monkeypatch.setattr(_tx_mod, "send_receipt_email", no_mail)
        monkeypatch.setattr(_tx_mod, "create_session_invoice", no_invoice)
        monkeypatch.setattr(stripe.PaymentIntent, "capture", capture)
        monkeypatch.setattr(stripe.PaymentIntent, "cancel", cancel)
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_mock")

    def comes_back(self, ago_s):
        """A töltő ennyi mp-e csatlakozott vissza (és azóta üzenget)."""
        self.online = True
        self.connected_at = utcnow() - timedelta(seconds=ago_s)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(_tx_mod, "AsyncSessionLocal", TestSession)
    ps.reset_state()
    yield _World(monkeypatch)
    ps.reset_state()


async def _cp(online_seen=False):
    """A töltő; offline-nál a last_seen_at régi (compute_status → offline)."""
    async with TestSession() as s:
        seen = utcnow() if online_seen else utcnow() - timedelta(minutes=10)
        cp = ChargePoint(ocpp_id=CP, status="available", last_seen_at=seen, is_published=True)
        s.add(cp)
        await s.commit()
        return cp.id


async def _touch_cp():
    async with TestSession() as s:
        cp = (await s.execute(select(ChargePoint).where(ChargePoint.ocpp_id == CP))).scalar_one()
        cp.last_seen_at = utcnow()
        await s.commit()


async def _paid(cp_id, age_min=6, offline_since_min=None, connector_id=1):
    """A Stripe-webhook által létrehozott, kifizetett, el nem indult munkamenet."""
    async with TestSession() as s:
        intent = ChargingIntent(
            charge_point_id=cp_id, connector_id=connector_id, anonymous_email="ugyfel@example.hu",
            status="paid", hold_amount_huf=5000, expires_at=utcnow(),
            payment_provider="stripe", payment_provider_ref="cs_test_1", stripe_payment_intent_id="pi_test_1",
        )
        s.add(intent)
        await s.flush()
        cs = ChargeSession(
            charge_point_id=cp_id, connector_id=connector_id, started_at=utcnow() - timedelta(minutes=age_min),
            anonymous_email="ugyfel@example.hu", intent_id=intent.id,
            offline_wait_since=(utcnow() - timedelta(minutes=offline_since_min)
                                if offline_since_min is not None else None),
        )
        s.add(cs)
        await s.commit()
        return cs.id


async def _session(sid):
    async with TestSession() as s:
        return (await s.execute(select(ChargeSession).where(ChargeSession.id == sid))).scalar_one()


def _ts(dt):
    return dt.isoformat().replace("+00:00", "Z")


def _logs(caplog, needle):
    return [r.getMessage() for r in caplog.records if needle in r.getMessage()]


# ── Lejárati kör ─────────────────────────────────────────────────────────────

async def test_offline_after_window_waits_and_keeps_hold(world, caplog):
    """fizetés → offline → 5 perc → nem zár, nem old fel, nem küld „nem indult el” e-mailt."""
    cp_id = await _cp()
    sid = await _paid(cp_id, age_min=6)

    with caplog.at_level(logging.WARNING):
        await main._expire_waiting_sessions_once()
    cs = await _session(sid)
    assert cs.finished_at is None and cs.offline_wait_since is not None
    assert world.released == [] and world.no_start == []
    assert len(_logs(caplog, f"OfflineWait: session_id={sid}")) == 1

    # Később is offline (pl. 1 óra múlva): marad várakozásban, újabb naplósor sem jön
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        await main._expire_waiting_sessions_once()
    assert (await _session(sid)).finished_at is None
    assert world.released == [] and world.no_start == []
    assert _logs(caplog, "OfflineWait") == []


async def test_online_charger_keeps_old_behaviour(world):
    """Online töltő, nem indult el → lezárás + feloldás + „nem indult el” e-mail (az alapszöveggel)."""
    world.comes_back(ago_s=3600)
    cp_id = await _cp(online_seen=True)
    sid = await _paid(cp_id, age_min=6)

    await main._expire_waiting_sessions_once()
    cs = await _session(sid)
    assert cs.finished_at is not None and cs.offline_wait_since is None
    assert world.released == [("cs_test_1", sid)]
    assert len(world.no_start) == 1 and world.no_start[0]["reason"] is None


async def test_within_window_not_touched(world):
    cp_id = await _cp()
    sid = await _paid(cp_id, age_min=3)
    await main._expire_waiting_sessions_once()
    cs = await _session(sid)
    assert cs.finished_at is None and cs.offline_wait_since is None


async def test_back_without_start_releases(world, caplog):
    """Visszajön, de a türelmi időn belül nem jön StartTransaction → lezárás + feloldás."""
    cp_id = await _cp()
    sid = await _paid(cp_id, age_min=40, offline_since_min=34)

    # Most jött vissza: még a türelmi időn belül → vár
    world.comes_back(ago_s=30)
    await _touch_cp()
    await main._expire_waiting_sessions_once()
    assert (await _session(sid)).finished_at is None
    assert world.released == []

    # A türelmi idő letelt, StartTransaction nem jött
    world.comes_back(ago_s=ps.RECONNECT_GRACE_S + 5)
    with caplog.at_level(logging.WARNING):
        await main._expire_waiting_sessions_once()
    cs = await _session(sid)
    assert cs.finished_at is not None and cs.ocpp_transaction_id is None
    assert world.released == [("cs_test_1", sid)]
    assert len(world.no_start) == 1 and "megszakadt a kapcsolat" in world.no_start[0]["reason"]
    assert len(_logs(caplog, f"session_id={sid} cp={CP} – visszajött")) == 1


async def test_24h_limit_releases(world, caplog):
    cp_id = await _cp()
    sid = await _paid(cp_id, age_min=ps.OFFLINE_WAIT_MAX_HOURS * 60 + 1, offline_since_min=24 * 60)

    with caplog.at_level(logging.WARNING):
        await main._expire_waiting_sessions_once()
    cs = await _session(sid)
    assert cs.finished_at is not None
    assert world.released == [("cs_test_1", sid)]
    assert len(world.no_start) == 1 and "24 órán belül" in world.no_start[0]["reason"]
    assert len(_logs(caplog, f"OfflineWait lejárt: session_id={sid}")) == 1


# ── Visszacsatlakozás: a sorba állított StartTransaction ─────────────────────

@pytest.mark.parametrize("meter_stop,capture_huf", [
    (11_000, 1700),    # 10 kWh × 170 Ft = 1700 Ft
    (41_000, 5000),    # 40 kWh × 170 Ft = 6800 Ft → legfeljebb a zárolt 5000 Ft
])
async def test_back_with_start_in_window_binds_and_captures(world, caplog, meter_stop, capture_huf):
    cp_id = await _cp()
    sid = await _paid(cp_id, age_min=50, offline_since_min=44)
    paid_at = (await _session(sid)).started_at
    world.comes_back(ago_s=2)

    started = paid_at + timedelta(minutes=3)   # net nélkül indult, 3 perccel a fizetés után
    with caplog.at_level(logging.WARNING):
        tx = await _tx_mod.start_transaction(CP, {
            "connectorId": 1, "idTag": "ANON", "meterStart": 1000, "timestamp": _ts(started)})
    assert tx == sid
    cs = await _session(sid)
    assert cs.ocpp_transaction_id == str(sid) and cs.meter_start_wh == 1000
    assert cs.started_at.replace(tzinfo=None) == started.replace(tzinfo=None)
    assert len(_logs(caplog, f"OfflineWait: session_id={sid} cp={CP} connector=1 – visszajött és indult")) == 1

    # Elindult → a lejárati kör már nem nyúl hozzá
    await main._expire_waiting_sessions_once()
    assert (await _session(sid)).finished_at is None and world.released == []

    await _tx_mod.stop_transaction(CP, {
        "transactionId": sid, "meterStop": meter_stop, "timestamp": _ts(started + timedelta(minutes=40))})
    cs = await _session(sid)
    assert cs.finished_at is not None
    assert world.captures == [("pi_test_1", capture_huf * 100)]
    assert world.cancels == [] and world.no_start == []


async def test_late_start_not_bound(world, caplog):
    """Órákkal később, helyben indított töltés → nem az ügyfélé: új munkamenet + figyelmeztetés."""
    cp_id = await _cp()
    sid = await _paid(cp_id, age_min=300, offline_since_min=294)
    paid_at = (await _session(sid)).started_at
    world.comes_back(ago_s=2)

    with caplog.at_level(logging.WARNING):
        tx = await _tx_mod.start_transaction(CP, {
            "connectorId": 1, "idTag": "ANON", "meterStart": 1000,
            "timestamp": _ts(paid_at + timedelta(hours=4))})
    assert tx is not None and tx != sid
    cs = await _session(sid)
    assert cs.ocpp_transaction_id is None and cs.finished_at is None
    new = await _session(tx)
    assert new.intent_id is None
    assert len(_logs(caplog, "StartTransaction az ablakon kívül")) == 1

    # A türelmi idő után a várakozó munkamenet feloldódik
    world.comes_back(ago_s=ps.RECONNECT_GRACE_S + 5)
    await _touch_cp()
    await main._expire_waiting_sessions_once()
    assert (await _session(sid)).finished_at is not None
    assert world.released == [("cs_test_1", sid)]


async def test_start_before_payment_not_bound(world):
    cp_id = await _cp()
    sid = await _paid(cp_id, age_min=30, offline_since_min=24)
    paid_at = (await _session(sid)).started_at
    tx = await _tx_mod.start_transaction(CP, {
        "connectorId": 1, "idTag": "ANON", "meterStart": 0, "timestamp": _ts(paid_at - timedelta(minutes=10))})
    assert tx != sid and (await _session(sid)).ocpp_transaction_id is None


async def test_other_connector_not_bound(world):
    """Offline-ra váró munkamenethez csak ugyanarról a csatlakozóról kötünk."""
    cp_id = await _cp()
    sid = await _paid(cp_id, age_min=30, offline_since_min=24, connector_id=1)
    paid_at = (await _session(sid)).started_at
    tx = await _tx_mod.start_transaction(CP, {
        "connectorId": 2, "idTag": "ANON", "meterStart": 0, "timestamp": _ts(paid_at + timedelta(minutes=2))})
    assert tx != sid and (await _session(sid)).ocpp_transaction_id is None


async def test_no_remote_start_for_offline_waiting(world, monkeypatch):
    """Visszacsatlakozáskor (boot / Preparing) offline-ra váró munkamenetre nem megy RemoteStart."""
    calls = []

    async def fake(cp_id, connector_id=1, id_tag="ANON"):
        calls.append(cp_id)
        return {"status": "Accepted"}

    monkeypatch.setattr(reg, "remote_start_transaction", fake)
    monkeypatch.setattr(ps, "_RECONNECT_DELAY_S", 0)
    cp_id = await _cp()
    sid = await _paid(cp_id, age_min=20, offline_since_min=14)
    world.comes_back(ago_s=1)

    await ps.retry_pending_remote_start(CP)
    await ps.retry_on_preparing(CP, 1)
    out = await ps.retry_remote_start(sid, reason="test")
    assert calls == [] and out["skipped"] == "offline_wait"


# ── Ügyfél- és admin-oldal ───────────────────────────────────────────────────

async def test_api_shows_offline_wait(world, client, monkeypatch):
    from app.services.auth_tokens import issue_intent_token
    monkeypatch.setenv("AUTH_SECRET", "teszt-titok")
    cp_id = await _cp()
    sid = await _paid(cp_id, age_min=20, offline_since_min=14)
    cs = await _session(sid)

    r = await client.get(f"/api/sessions/by-intent/{cs.intent_id}",
                         headers={"X-Intent-Token": issue_intent_token(cs.intent_id)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["offline_wait"] is True and body["is_active"] is True and body["timed_out"] is False
    assert body["offline_wait_until"].startswith(
        (cs.started_at + timedelta(hours=ps.OFFLINE_WAIT_MAX_HOURS)).isoformat()[:16])

    r = await client.get("/api/admin/sessions", headers=ADMIN_AUTH)
    row = next(x for x in r.json() if x["id"] == sid)
    assert row["offline_wait"] is True and row["offline_wait_until"]

    # Admin force-close rá is működik: lezár, a Stripe-zárolást feloldja (0 Ft → cancel)
    r = await client.post(f"/api/admin/sessions/{sid}/force-close", headers=ADMIN_AUTH)
    assert r.status_code == 200 and r.json()["session"]["offline_wait"] is False
    assert world.cancels == ["pi_test_1"]
