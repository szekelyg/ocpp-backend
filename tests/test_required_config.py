"""Kötelező töltő-beállítások, 5 perces várakozási ablak a fizetéstől, foglaltság.

2026-10-30, Gellért döntése: minden töltőn ConnectionTimeOut = 300 (= a függő munkamenet
lejárata), és nincs offline töltés (LocalAuthorizeOffline / AllowOfflineTxForUnknownId = false).
Bootkor magától, kézzel az adminból egy vagy az összes töltőre.
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

import app.ocpp.registry as reg
import app.ocpp.required_config as rc
from app.db.models import ChargePoint, ChargeSession, ChargingIntent, Location
from app.ocpp.handlers.pending_start import WAITING_TIMEOUT_MINUTES
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession

ADMIN_AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:test-admin-pw").decode()}

# A gyári (eltérő) értékek, ahogy a norg_onk_2-n voltak
FACTORY = {"ConnectionTimeOut": "60", "LocalAuthorizeOffline": "true", "AllowOfflineTxForUnknownId": "true"}


class _FakeCharger:
    """Állapotos töltő: a GetConfiguration a tárolt értéket adja, a ChangeConfiguration
    a megadott választ (alap: Accepted → az érték átíródik)."""
    def __init__(self, monkeypatch, values=None, answers=None, unknown=(), online=("norg_onk_2",)):
        self.values = {cp: dict(values or FACTORY) for cp in online}
        self.answers = answers or {}
        self.unknown = set(unknown)
        self.changes = []
        self.reads = 0
        online = set(online)

        async def get_ws(cp_id):
            return object() if cp_id in online else None

        async def connected_ids():
            return sorted(online)

        async def send_call_and_wait(cp_id, action, payload, timeout_s=12.0):
            assert action == "GetConfiguration"
            self.reads += 1
            vals = self.values[cp_id]
            return {
                "configurationKey": [{"key": k, "value": vals[k], "readonly": False}
                                     for k in payload["key"] if k in vals and k not in self.unknown],
                "unknownKey": [k for k in payload["key"] if k in self.unknown],
            }

        async def change_configuration(cp_id, key, value):
            self.changes.append((cp_id, key, value))
            status = self.answers.get(key, "Accepted")
            if status == "Accepted":
                self.values[cp_id][key] = value
            return {"status": status}

        monkeypatch.setattr(reg, "get_ws", get_ws)
        monkeypatch.setattr(reg, "connected_ids", connected_ids)
        monkeypatch.setattr(reg, "send_call_and_wait", send_call_and_wait)
        monkeypatch.setattr(reg, "change_configuration", change_configuration)


async def _cp(ocpp_id="norg_onk_2", published=False):
    async with TestSession() as s:
        loc = Location(name="Nógrád, vár", latitude=47.9, longitude=19.5)
        s.add(loc)
        await s.flush()
        cp = ChargePoint(ocpp_id=ocpp_id, location_id=loc.id, connector_type="Type 2", max_power_kw=22.0,
                         status="available", last_seen_at=utcnow(), is_published=published)
        s.add(cp)
        await s.commit()
        return cp.id


async def _stored(ocpp_id="norg_onk_2"):
    async with TestSession() as s:
        return (await s.execute(select(ChargePoint.required_config_state)
                                .where(ChargePoint.ocpp_id == ocpp_id))).scalar_one()


def test_required_values():
    assert rc.REQUIRED_CONFIG == {
        "ConnectionTimeOut": "300",
        "LocalAuthorizeOffline": "false",
        "AllowOfflineTxForUnknownId": "false",
    }
    assert rc.REQUIRED_CONFIG["ConnectionTimeOut"] == str(WAITING_TIMEOUT_MINUTES * 60)


# ── Alkalmazás ───────────────────────────────────────────────────────────────

async def test_differing_values_changed_read_back_and_stored(monkeypatch, caplog):
    await _cp()
    charger = _FakeCharger(monkeypatch)

    with caplog.at_level(logging.INFO, logger="ocpp"):
        state = await rc.apply_required_config("norg_onk_2", "boot")

    assert sorted(charger.changes) == sorted(("norg_onk_2", k, v) for k, v in rc.REQUIRED_CONFIG.items())
    assert charger.reads == 2, "előtte kiolvas, utána visszaolvas"
    assert state["summary"] == "ok"
    assert state["keys"]["ConnectionTimeOut"] == {"old": "60", "want": "300", "status": "Accepted", "new": "300"}
    stored = await _stored()
    assert stored["summary"] == "ok" and stored["reason"] == "boot"
    assert stored["keys"]["LocalAuthorizeOffline"]["new"] == "false"
    msgs = [r.getMessage() for r in caplog.records]
    assert any("cp=norg_onk_2 ConnectionTimeOut 60 -> 300 status=Accepted visszaolvasva=300" in m for m in msgs)


async def test_already_ok_sends_nothing(monkeypatch):
    await _cp()
    # a Voltie nagybetűvel is adhatja vissza a logikai értéket
    charger = _FakeCharger(monkeypatch, values={"ConnectionTimeOut": "300", "LocalAuthorizeOffline": "False",
                                                "AllowOfflineTxForUnknownId": "false"})
    state = await rc.apply_required_config("norg_onk_2", "boot")
    assert charger.changes == [] and charger.reads == 1
    assert state["summary"] == "ok"


async def test_rejecting_charger_flagged_not_retried(monkeypatch, caplog):
    await _cp()
    charger = _FakeCharger(monkeypatch, answers={"LocalAuthorizeOffline": "Rejected"},
                           unknown={"AllowOfflineTxForUnknownId"})
    with caplog.at_level(logging.WARNING, logger="ocpp"):
        state = await rc.apply_required_config("norg_onk_2", "boot")

    assert state["summary"] == "rejected"
    assert state["keys"]["LocalAuthorizeOffline"]["status"] == "Rejected"
    assert state["keys"]["LocalAuthorizeOffline"]["new"] == "true"
    assert state["keys"]["AllowOfflineTxForUnknownId"]["status"] == "NotSupported"
    assert state["keys"]["ConnectionTimeOut"]["status"] == "Accepted"
    # kulcsonként legfeljebb egy ChangeConfiguration, a nem ismert kulcsra semmi
    assert sorted(k for _, k, _ in charger.changes) == ["ConnectionTimeOut", "LocalAuthorizeOffline"]
    assert (await _stored())["summary"] == "rejected"
    assert any("eredmény=rejected" in r.getMessage() for r in caplog.records)


async def test_reboot_required_is_differs(monkeypatch):
    await _cp()
    _FakeCharger(monkeypatch, answers={"ConnectionTimeOut": "RebootRequired"})
    state = await rc.apply_required_config("norg_onk_2", "boot")
    assert state["summary"] == "differs"
    assert state["keys"]["ConnectionTimeOut"]["status"] == "RebootRequired"


async def test_no_loop_concurrent_triggers_run_once(monkeypatch):
    await _cp()
    charger = _FakeCharger(monkeypatch, answers={"LocalAuthorizeOffline": "Rejected"})
    a, b = await asyncio.gather(rc.apply_required_config("norg_onk_2", "boot"),
                                rc.apply_required_config("norg_onk_2", "boot"))
    assert sorted([a["summary"], b["summary"]]) == ["busy", "rejected"]
    assert len([c for c in charger.changes if c[1] == "LocalAuthorizeOffline"]) == 1


async def test_offline_charger_error_stored(monkeypatch):
    await _cp()

    async def boom(*a, **kw):
        raise RuntimeError("Nincs aktív WS kapcsolat")
    monkeypatch.setattr(reg, "send_call_and_wait", boom)
    state = await rc.apply_required_config("norg_onk_2", "boot")
    assert state["summary"] == "error" and "WS" in state["error"]
    assert (await _stored())["summary"] == "error"


def test_boot_notification_triggers_once(monkeypatch):
    """BootNotification → apply_required_config(cp, "boot") egyszer."""
    import app.ocpp.ws as ws_mod
    import app.ocpp.handlers.boot as boot_mod
    from app.main import app

    monkeypatch.setattr(boot_mod, "AsyncSessionLocal", TestSession)
    calls = []

    async def record(cp_id, reason):
        calls.append((cp_id, reason))
        return {"summary": "ok"}

    async def noop(*a, **kw):
        return None
    monkeypatch.setattr(ws_mod, "apply_required_config", record)
    for name in ("retry_pending_remote_start", "_set_meter_interval", "_set_display_text", "rebalance_for_cp"):
        monkeypatch.setattr(ws_mod, name, noop)

    asyncio.run(_cp())
    with TestClient(app).websocket_connect("/ocpp/norg_onk_2") as ws:
        ws.send_text(json.dumps([2, "b1", "BootNotification",
                                 {"chargePointVendor": "Voltie", "chargePointModel": "Base"}]))
        assert json.loads(ws.receive_text())[2]["status"] == "Accepted"
        ws.send_text(json.dumps([2, "h1", "Heartbeat", {}]))
        ws.receive_text()
    assert calls == [("norg_onk_2", "boot")]


# ── Admin ────────────────────────────────────────────────────────────────────

async def test_admin_apply_one(client, monkeypatch):
    cp_id = await _cp()
    charger = _FakeCharger(monkeypatch)

    assert (await client.post(f"/api/admin/charge-points/{cp_id}/required-config")).status_code == 401
    assert charger.changes == []

    r = await client.post(f"/api/admin/charge-points/{cp_id}/required-config", headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert r.json()["ok"] and r.json()["state"]["summary"] == "ok"
    assert len(charger.changes) == 3
    assert (await _stored())["reason"] == "admin:admin"

    # az admin töltőlista mutatja
    rows = (await client.get("/api/admin/charge-points", headers=ADMIN_AUTH)).json()
    row = next(c for c in (rows if isinstance(rows, list) else rows["items"]) if c["id"] == cp_id)
    assert row["required_config"]["summary"] == "ok"


async def test_admin_apply_one_offline(client, monkeypatch):
    cp_id = await _cp()
    _FakeCharger(monkeypatch, online=())
    r = await client.post(f"/api/admin/charge-points/{cp_id}/required-config", headers=ADMIN_AUTH)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "charger_offline"


async def test_admin_apply_all_connected(client, monkeypatch):
    await _cp("norg_onk_1")
    await _cp("norg_onk_2")
    await _cp("offline_tolto")
    charger = _FakeCharger(monkeypatch, online=("norg_onk_1", "norg_onk_2"),
                           answers={"AllowOfflineTxForUnknownId": "Rejected"})

    assert (await client.post("/api/admin/charge-points/required-config")).status_code == 401

    r = await client.post("/api/admin/charge-points/required-config", headers=ADMIN_AUTH)
    assert r.status_code == 200
    body = r.json()
    assert set(body["results"]) == {"norg_onk_1", "norg_onk_2"}
    assert all(v["summary"] == "rejected" for v in body["results"].values())
    assert body["ok"] is False
    assert {c[0] for c in charger.changes} == {"norg_onk_1", "norg_onk_2"}
    assert await _stored("offline_tolto") is None


async def test_admin_config_allowlist_unchanged(client, monkeypatch):
    """A kötelező kulcsok nem nyitják meg a kézi ChangeConfiguration-t."""
    cp_id = await _cp()
    _FakeCharger(monkeypatch)
    for key in ("LocalAuthorizeOffline", "AllowOfflineTxForUnknownId", "AuthorizationKey"):
        r = await client.post(f"/api/admin/charge-points/{cp_id}/config", headers=ADMIN_AUTH,
                              json={"key": key, "value": "true"})
        assert r.status_code == 400


# ── 5 perces ablak a fizetéstől ──────────────────────────────────────────────

async def _paid_session(cp_id, paid_min_ago, intent_created_min_ago):
    async with TestSession() as s:
        intent = ChargingIntent(
            charge_point_id=cp_id, connector_id=1, anonymous_email="ugyfel@example.hu", status="paid",
            hold_amount_huf=5000, payment_provider="stripe", payment_provider_ref="cs_test",
            created_at=utcnow() - timedelta(minutes=intent_created_min_ago),
            expires_at=utcnow() - timedelta(minutes=intent_created_min_ago) + timedelta(minutes=15),
        )
        s.add(intent)
        await s.flush()
        cs = ChargeSession(charge_point_id=cp_id, connector_id=1, started_at=utcnow() - timedelta(minutes=paid_min_ago),
                           anonymous_email="ugyfel@example.hu", intent_id=intent.id)
        s.add(cs)
        await s.commit()
        return cs.id


async def test_waiting_window_five_minutes_from_payment(monkeypatch):
    import app.main as main_mod
    import app.services.email as email_mod

    released, mailed = [], []

    async def fake_release(ref, sid):
        released.append(sid)

    async def fake_mail(**kw):
        mailed.append(kw["session_id"])
        return True
    monkeypatch.setattr(main_mod, "_try_stripe_cancel_or_refund", fake_release)
    monkeypatch.setattr(email_mod, "send_no_start_email", fake_mail)

    async def online(cp_id):
        return object()   # a töltő csatlakozik (offline töltőnél várnánk: test_offline_wait.py)
    monkeypatch.setattr(reg, "get_ws", online)

    assert WAITING_TIMEOUT_MINUTES == 5
    cp_id = await _cp()
    # 14 perce nyitotta a fizetést, de csak 1 perce fizetett → még vár
    fresh = await _paid_session(cp_id, paid_min_ago=1, intent_created_min_ago=14)
    # 6 perce fizetett → lejárt
    old = await _paid_session(cp_id, paid_min_ago=6, intent_created_min_ago=7)

    await main_mod._expire_waiting_sessions_once()

    async with TestSession() as s:
        rows = {c.id: c for c in (await s.execute(select(ChargeSession))).scalars().all()}
    assert rows[fresh].finished_at is None
    assert rows[old].finished_at is not None
    assert released == [old] and mailed == [old]


# ── Foglaltság ───────────────────────────────────────────────────────────────

_INTENT_BODY = {
    "connector_id": 1, "email": "masodik@example.hu", "hold_amount_huf": 5000,
    "billing_type": "personal", "billing_name": "Teszt Elek", "billing_street": "Fő u. 1.",
    "billing_zip": "1051", "billing_city": "Budapest", "billing_country": "HU",
}


async def test_new_intent_blocked_while_paid_session_pending(client):
    cp_id = await _cp(published=True)
    await _paid_session(cp_id, paid_min_ago=1, intent_created_min_ago=2)

    r = await client.post("/api/intents/", json={**_INTENT_BODY, "charge_point_id": cp_id})
    assert r.status_code == 409
    assert r.json()["detail"] == {"error": "charge_point_busy",
                                  "hint": "A töltőt épp más használja, próbálja pár perc múlva."}

