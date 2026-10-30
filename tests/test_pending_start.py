"""Függő (kifizetett, el nem indult) munkamenet RemoteStart-újraküldése.

2026-10-28, norg_onk_2: fizetés → RemoteStart → Accepted → Preparing, de a töltő
ConnectionTimeOut-ja (60 mp) lejárt, mielőtt az autó tölteni kezdett; visszaváltott
Available-re, a később bedugott autóhoz (Preparing) már nem volt engedély, StartTransaction
nem jött, 15 perc után a munkamenet 0 kWh-val lezárult. Most a Preparing-re a backend
újraküldi a RemoteStartot (korlátokkal), és ugyanez a függvény kézzel is hívható az adminból.
"""
import asyncio
import base64
import json
import logging
import os
from datetime import timedelta

os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ["ADMIN_PASSWORD"] = "test-admin-pw"

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

import app.ocpp.handlers.pending_start as ps
import app.ocpp.registry as reg
from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession

import app.ocpp.handlers.status as _status_mod
import app.ocpp.handlers.transactions as _tx_mod

ADMIN_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:test-admin-pw").decode()}


# ── Segédek ──────────────────────────────────────────────────────────────────

class _Clock:
    """A MIN_GAP_S-hez kézzel léptetett óra."""
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    # A handlerek import-időben kötik az AsyncSessionLocal-t → a teszt DB-re irányítjuk.
    monkeypatch.setattr(_status_mod, "AsyncSessionLocal", TestSession)
    monkeypatch.setattr(_tx_mod, "AsyncSessionLocal", TestSession)
    monkeypatch.setattr(ps, "_RECONNECT_DELAY_S", 0)
    clock = _Clock()
    monkeypatch.setattr(ps, "_clock", clock)
    ps.reset_state()
    yield clock
    ps.reset_state()


class _FakeStart:
    """registry.remote_start_transaction helyett: rögzíti a hívásokat, a megadott választ adja."""
    def __init__(self, monkeypatch, status="Accepted", raises=None):
        self.calls = []

        async def fake(cp_id, connector_id=1, id_tag="ANON"):
            self.calls.append((cp_id, connector_id, id_tag))
            if raises:
                raise raises
            return {"status": status}

        monkeypatch.setattr(reg, "remote_start_transaction", fake)


async def _cp(ocpp_id="norg_onk_2"):
    async with TestSession() as s:
        cp = ChargePoint(ocpp_id=ocpp_id, status="available", last_seen_at=utcnow(), is_published=True)
        s.add(cp)
        await s.commit()
        return cp.id


async def _pending(cp_id, connector_id=1, age_min=1, intent_status="paid", tx=None, finished=False):
    """Amit a Stripe-webhook hoz létre: kifizetett intent + session, tx nélkül."""
    async with TestSession() as s:
        intent = ChargingIntent(
            charge_point_id=cp_id, connector_id=connector_id, anonymous_email="ugyfel@example.hu",
            status=intent_status, hold_amount_huf=5000, expires_at=utcnow(),
        )
        s.add(intent)
        await s.flush()
        started = utcnow() - timedelta(minutes=age_min)
        cs = ChargeSession(
            charge_point_id=cp_id, connector_id=connector_id, ocpp_transaction_id=tx,
            started_at=started, finished_at=started if finished else None,
            anonymous_email="ugyfel@example.hu", intent_id=intent.id,
        )
        s.add(cs)
        await s.commit()
        return cs.id


async def _session(sid):
    async with TestSession() as s:
        return (await s.execute(select(ChargeSession).where(ChargeSession.id == sid))).scalar_one()


# ── Teljes folyamat a valódi OCPP-websocketen ────────────────────────────────

def test_paid_then_available_then_preparing_restarts_and_charges(monkeypatch, _setup):
    """fizetés → RemoteStart → Available (lejárt a töltő ideje) → később Preparing →
    automatikus RemoteStart → StartTransaction → a kifizetett munkamenet elindul."""
    import app.api.routers.payments_stripe as pay
    from app.main import app

    clock = _setup

    async def seed():
        cp_id = await _cp()
        async with TestSession() as s:
            intent = ChargingIntent(charge_point_id=cp_id, connector_id=1, anonymous_email="ugyfel@example.hu",
                                    status="pending_payment", hold_amount_huf=5000, expires_at=utcnow())
            s.add(intent)
            await s.commit()
            return intent.id

    async def pay_intent(intent_id):
        async def no_mail(**kw):
            return True
        with monkeypatch.context() as m:
            m.setattr(pay, "send_charging_started_email", no_mail)
            m.setenv("AUTH_SECRET", "teszt-titok")
            fake = _FakeStart(m)
            async with TestSession() as db:
                intent = (await db.execute(select(ChargingIntent).where(ChargingIntent.id == intent_id))).scalar_one()
                res = await pay._ensure_session_and_remote_start(db, intent, "cs_test_48")
                await db.commit()
        assert fake.calls == [("norg_onk_2", 1, "ANON")], "fizetés után az első RemoteStart"
        return res["session_id"]

    intent_id = asyncio.run(seed())
    session_id = asyncio.run(pay_intent(intent_id))

    def call(uid, action, payload):
        return json.dumps([2, uid, action, payload])

    # Lifespan (háttér-körök) nélkül: azok saját időzítéssel írnák a teszt-DB-t
    with TestClient(app).websocket_connect("/ocpp/norg_onk_2") as ws:
        # A töltő 59 mp múlva visszavált Available-re (lejárt a ConnectionTimeOut)
        clock.t += 59
        ws.send_text(call("s1", "StatusNotification", {"connectorId": 1, "status": "Available", "errorCode": "NoError"}))
        assert json.loads(ws.receive_text()) == [3, "s1", {}]

        # Később bedugják az autót → Preparing → a backend újraküldi a RemoteStartot
        clock.t += 60
        ws.send_text(call("s2", "StatusNotification", {"connectorId": 1, "status": "Preparing", "errorCode": "NoError"}))
        assert json.loads(ws.receive_text()) == [3, "s2", {}]
        frame = json.loads(ws.receive_text())
        assert frame[0] == 2 and frame[2] == "RemoteStartTransaction"
        assert frame[3] == {"connectorId": 1, "idTag": "ANON"}
        ws.send_text(json.dumps([3, frame[1], {"status": "Accepted"}]))

        # A töltő elindítja a tranzakciót → a kifizetett munkamenethez kötjük
        ws.send_text(call("s3", "StartTransaction", {"connectorId": 1, "idTag": "ANON", "meterStart": 1000,
                                                     "timestamp": "2026-10-28T13:58:00Z"}))
        res = json.loads(ws.receive_text())
        assert res[1] == "s3" and res[2]["transactionId"] == session_id

    cs = asyncio.run(_session(session_id))
    assert cs.ocpp_transaction_id == str(session_id)
    assert cs.finished_at is None
    assert cs.intent_id == intent_id


# ── Korlátok ─────────────────────────────────────────────────────────────────

async def test_preparing_right_after_payment_start_does_not_resend(monkeypatch, _setup):
    """A RemoteStart után szokásos Preparing (pár mp) nem vált ki újraküldést (MIN_GAP_S)."""
    clock = _setup
    cp_id = await _cp()
    sid = await _pending(cp_id)
    fake = _FakeStart(monkeypatch)

    await ps.send_remote_start("norg_onk_2", sid, None, 1, reason="payment")   # fizetés utáni első
    clock.t += 3
    await ps.retry_on_preparing("norg_onk_2", 1)
    assert len(fake.calls) == 1

    clock.t += ps.MIN_GAP_S
    await ps.retry_on_preparing("norg_onk_2", 1)
    assert len(fake.calls) == 2, "a szünet után már újraküld"

    clock.t += 5
    await ps.retry_on_preparing("norg_onk_2", 1)
    assert len(fake.calls) == 2, "két küldés között legalább MIN_GAP_S"


async def test_max_auto_retries(monkeypatch, _setup):
    clock = _setup
    cp_id = await _cp()
    await _pending(cp_id)
    fake = _FakeStart(monkeypatch)

    for _ in range(ps.MAX_AUTO_RETRIES + 3):
        clock.t += ps.MIN_GAP_S + 1
        await ps.retry_on_preparing("norg_onk_2", 1)
    assert len(fake.calls) == ps.MAX_AUTO_RETRIES


async def test_reconnect_and_preparing_share_the_limit(monkeypatch, _setup):
    """Boot és Preparing egyszerre: csak az egyik küld (közös számláló, közös szünet)."""
    cp_id = await _cp()
    await _pending(cp_id)
    fake = _FakeStart(monkeypatch)

    await asyncio.gather(ps.retry_pending_remote_start("norg_onk_2"), ps.retry_on_preparing("norg_onk_2", 1))
    assert len(fake.calls) == 1


@pytest.mark.parametrize("kw", [
    {"age_min": 20},                         # lejárt (a waiting timeout előtt 1 perccel feladjuk)
    {"tx": "123"},                           # már elindult (StartTransaction megjött)
    {"finished": True},                      # lezárva / törölve
    {"intent_status": "pending_payment"},    # nincs kifizetve
])
async def test_no_resend_when_not_pending(monkeypatch, kw):
    cp_id = await _cp()
    sid = await _pending(cp_id, **kw)
    fake = _FakeStart(monkeypatch)

    await ps.retry_on_preparing("norg_onk_2", 1)
    await ps.retry_pending_remote_start("norg_onk_2")
    out = await ps.retry_remote_start(sid, reason="test")
    assert fake.calls == []
    assert out["sent"] is False and out["skipped"]


async def test_only_matching_connector(monkeypatch):
    cp_id = await _cp()
    await _pending(cp_id, connector_id=1)
    fake = _FakeStart(monkeypatch)

    await ps.retry_on_preparing("norg_onk_2", 2)   # másik csatlakozó
    await ps.retry_on_preparing("norg_onk_2", 0)   # állomás-szintű állapot
    await ps.retry_on_preparing("masik_tolto", 1)  # másik töltő
    assert fake.calls == []


async def test_resend_logged_with_cp_intent_session_and_answer(monkeypatch, caplog):
    cp_id = await _cp()
    sid = await _pending(cp_id)
    _FakeStart(monkeypatch, status="Rejected")

    with caplog.at_level(logging.INFO, logger="ocpp"):
        out = await ps.retry_remote_start(sid, reason="preparing")
    assert out["sent"] and out["ocpp"] == {"status": "Rejected"}
    line = next(r.getMessage() for r in caplog.records if "RemoteStart [preparing]" in r.getMessage())
    assert "cp=norg_onk_2" in line and f"session={sid}" in line and "intent=" in line and "Rejected" in line


async def test_charger_offline_is_logged_not_raised(monkeypatch):
    cp_id = await _cp()
    sid = await _pending(cp_id)
    _FakeStart(monkeypatch, raises=RuntimeError("Nincs aktív WS kapcsolat"))

    out = await ps.retry_remote_start(sid, reason="preparing")
    assert out["sent"] and out["ocpp"]["status"] == "Error"


async def test_status_notification_info_log(caplog):
    await _cp()
    with caplog.at_level(logging.INFO, logger="ocpp"):
        await _status_mod.save_status_notification(
            "norg_onk_2", {"connectorId": 1, "status": "Preparing", "errorCode": "NoError"})
    assert any(r.getMessage() == "StatusNotification: cp=norg_onk_2 connector=1 status=Preparing"
               for r in caplog.records)


# ── Admin: ConnectionTimeOut ─────────────────────────────────────────────────

class _FakeCharger:
    """A töltő OCPP-oldala az admin-végpontokhoz."""
    def __init__(self, monkeypatch, online=True, answer=None):
        self.calls = []

        async def get_ws(cp_id):
            return object() if online else None

        async def send_call_and_wait(cp_id, action, payload, timeout_s=12.0):
            self.calls.append((action, cp_id, payload))
            if action == "GetConfiguration":
                return {"configurationKey": [{"key": "ConnectionTimeOut", "value": "60"}]}
            return answer or {"status": "Accepted"}

        async def change_configuration(cp_id, key, value):
            self.calls.append(("ChangeConfiguration", cp_id, key, value))
            return {"status": "Accepted"}

        async def remote_stop_transaction(cp_id, transaction_id):
            self.calls.append(("RemoteStopTransaction", cp_id, transaction_id))
            return answer or {"status": "Accepted"}

        monkeypatch.setattr(reg, "get_ws", get_ws)
        monkeypatch.setattr(reg, "send_call_and_wait", send_call_and_wait)
        monkeypatch.setattr(reg, "change_configuration", change_configuration)
        import app.ocpp.ocpp_ws as ocpp_ws
        monkeypatch.setattr(ocpp_ws, "remote_stop_transaction", remote_stop_transaction)


@pytest.mark.parametrize("value", ["59", "901", "abc", "", "-60"])
async def test_connection_timeout_out_of_range(client, monkeypatch, value):
    charger = _FakeCharger(monkeypatch)
    cp_id = await _cp()
    r = await client.post(f"/api/admin/charge-points/{cp_id}/config", headers=ADMIN_AUTH,
                          json={"key": "ConnectionTimeOut", "value": value})
    assert r.status_code == 422
    assert r.json()["detail"]["min"] == 60 and r.json()["detail"]["max"] == 900
    assert charger.calls == [], "tartományon kívüli értéket nem küldünk a töltőnek"


@pytest.mark.parametrize("value", ["60", "180", "900"])
async def test_connection_timeout_set_and_logged(client, monkeypatch, caplog, value):
    charger = _FakeCharger(monkeypatch)
    cp_id = await _cp()
    with caplog.at_level(logging.WARNING, logger="admin"):
        r = await client.post(f"/api/admin/charge-points/{cp_id}/config", headers=ADMIN_AUTH,
                              json={"key": "ConnectionTimeOut", "value": value})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["old"] == "60" and body["new"] == value and body["status"] == "Accepted"
    assert ("ChangeConfiguration", "norg_onk_2", "ConnectionTimeOut", value) in charger.calls
    assert any(f"key=ConnectionTimeOut 60 -> {value} status=Accepted by=admin" in r.getMessage()
               for r in caplog.records)


async def test_config_still_rejects_unknown_key(client, monkeypatch):
    _FakeCharger(monkeypatch)
    cp_id = await _cp()
    r = await client.post(f"/api/admin/charge-points/{cp_id}/config", headers=ADMIN_AUTH,
                          json={"key": "AuthorizationKey", "value": "x"})
    assert r.status_code == 400
    assert "ConnectionTimeOut" in r.json()["detail"]["allowed"]


# ── Admin: kézi indítás, zár-kioldás, leállítás ──────────────────────────────

@pytest.mark.parametrize("method_path", [
    "/api/admin/sessions/1/remote-start",
    "/api/admin/charge-points/1/unlock",
    "/api/admin/sessions/1/stop",
])
async def test_manual_commands_admin_only(client, monkeypatch, method_path):
    charger = _FakeCharger(monkeypatch)
    fake = _FakeStart(monkeypatch)
    cp_id = await _cp()
    await _pending(cp_id)
    assert (await client.post(method_path)).status_code == 401
    bad = {"Authorization": "Basic " + base64.b64encode(b"admin:rossz").decode()}
    assert (await client.post(method_path, headers=bad)).status_code == 401
    assert charger.calls == [] and fake.calls == []


async def test_manual_remote_start(client, monkeypatch, caplog, _setup):
    _FakeCharger(monkeypatch)
    fake = _FakeStart(monkeypatch)
    cp_id = await _cp()
    sid = await _pending(cp_id)
    # Az automatikus korlát már kimerült – a kézi indítás ettől még megy
    ps._state(sid).retries = ps.MAX_AUTO_RETRIES

    with caplog.at_level(logging.INFO):
        r = await client.post(f"/api/admin/sessions/{sid}/remote-start", headers=ADMIN_AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["ocpp"] == {"status": "Accepted"}
    assert fake.calls == [("norg_onk_2", 1, "ANON")]
    msgs = [r.getMessage() for r in caplog.records]
    assert any("RemoteStart [admin]" in m and f"session={sid}" in m for m in msgs)
    assert any(m.startswith(f"admin_remote_start session={sid}") and "by=admin" in m for m in msgs)

    # A kézi küldés beleszámít a szünetbe: rögtön utána a Preparing nem küld újra
    await ps.retry_on_preparing("norg_onk_2", 1)
    assert len(fake.calls) == 1


async def test_manual_remote_start_errors(client, monkeypatch):
    fake = _FakeStart(monkeypatch, status="Rejected")
    cp_id = await _cp()
    sid = await _pending(cp_id)

    _FakeCharger(monkeypatch, online=False)
    r = await client.post(f"/api/admin/sessions/{sid}/remote-start", headers=ADMIN_AUTH)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "charger_offline"
    assert "nem csatlakozik" in r.json()["detail"]["hint"]
    assert fake.calls == []

    _FakeCharger(monkeypatch, online=True)
    r = await client.post(f"/api/admin/sessions/{sid}/remote-start", headers=ADMIN_AUTH)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "remote_start_rejected"
    assert "elutasította" in r.json()["detail"]["hint"]

    started = await _pending(cp_id, tx="555")
    r = await client.post(f"/api/admin/sessions/{started}/remote-start", headers=ADMIN_AUTH)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "already_started"
    assert (await client.post("/api/admin/sessions/9999/remote-start", headers=ADMIN_AUTH)).status_code == 404


async def test_unlock_connector(client, monkeypatch, caplog):
    cp_id = await _cp()

    _FakeCharger(monkeypatch, online=False)
    r = await client.post(f"/api/admin/charge-points/{cp_id}/unlock", headers=ADMIN_AUTH)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "charger_offline"

    charger = _FakeCharger(monkeypatch, answer={"status": "Unlocked"})
    with caplog.at_level(logging.WARNING, logger="admin"):
        r = await client.post(f"/api/admin/charge-points/{cp_id}/unlock?connector_id=1", headers=ADMIN_AUTH)
    assert r.status_code == 200 and r.json()["ocpp"] == {"status": "Unlocked"}
    assert charger.calls == [("UnlockConnector", "norg_onk_2", {"connectorId": 1})]
    assert any("admin_unlock cp=norg_onk_2 connector=1 status=Unlocked by=admin" in r.getMessage()
               for r in caplog.records)

    _FakeCharger(monkeypatch, answer={"status": "UnlockFailed"})
    r = await client.post(f"/api/admin/charge-points/{cp_id}/unlock", headers=ADMIN_AUTH)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "unlock_failed"
    assert "UnlockFailed" in r.json()["detail"]["hint"]


async def test_admin_stop_logged(client, monkeypatch, caplog):
    cp_id = await _cp()
    sid = await _pending(cp_id, tx="777")

    charger = _FakeCharger(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="admin"):
        r = await client.post(f"/api/admin/sessions/{sid}/stop", headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert charger.calls == [("RemoteStopTransaction", "norg_onk_2", "777")]
    assert any(f"admin_stop session={sid} cp=norg_onk_2 tx=777" in r.getMessage() and "by=admin" in r.getMessage()
               for r in caplog.records)

    _FakeCharger(monkeypatch, online=False)
    r = await client.post(f"/api/admin/sessions/{sid}/stop", headers=ADMIN_AUTH)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "charger_offline"
