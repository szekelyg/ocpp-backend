"""Terheléselosztás közös betáplálású töltők között (app/services/load_balance.py).

- allocate(): tiszta kiosztás (nincs aktív → mindenki a maximumát; egy aktív → ő a csoport
  maximumát, a tétlen a maradékot/min 6 A; kettő aktív → fele-fele; a saját max korlátoz).
- rebalance_group(): DB-ből számol, a ChangeConfiguration-t csak változásnál küldi,
  offline tagnak nem küld (boot után újra), elutasított választ hibaként jegyzi.
- admin: PUT /api/admin/charge-points/{id} load_* mezők, GET /api/admin/load-groups.
"""
import base64
import os
from datetime import timedelta

os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ["ADMIN_PASSWORD"] = "test-admin-pw"

import pytest
from sqlalchemy import select

import app.ocpp.registry as registry
import app.services.load_balance as lb
from app.db.models import ChargePoint, ChargeSession
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession


def basic():
    return {"Authorization": "Basic " + base64.b64encode(b"admin:test-admin-pw").decode()}


# ── allocate ────────────────────────────────────────────────────────────────

def test_allocate_nobody_active_everyone_full():
    out = lb.allocate(32, [("a", 32, False), ("b", 32, False)])
    assert out == {"a": 32, "b": 32}


def test_allocate_one_active_gets_all_idle_gets_min():
    out = lb.allocate(32, [("a", 32, True), ("b", 32, False)])
    assert out == {"a": 32, "b": 6}


def test_allocate_two_active_half_half():
    out = lb.allocate(32, [("a", 32, True), ("b", 32, True)])
    assert out == {"a": 16, "b": 16}


def test_allocate_three_active_and_cap():
    out = lb.allocate(32, [("a", 32, True), ("b", 32, True), ("c", 32, True)])
    assert out == {"a": 10, "b": 10, "c": 10}
    # a saját max (16 A-es töltő) korlátoz, a maradék a másiké
    out = lb.allocate(32, [("a", 16, True), ("b", 32, False)])
    assert out == {"a": 16, "b": 16}
    out = lb.allocate(32, [("a", 16, True), ("b", 32, True)])
    assert out == {"a": 16, "b": 16}


def test_allocate_never_below_min():
    out = lb.allocate(20, [("a", 32, True), ("b", 32, True), ("c", 32, True), ("d", 32, True)])
    assert all(v == lb.MIN_A for v in out.values())


# ── rebalance_group (DB + OCPP-mock) ─────────────────────────────────────────

class _Fake:
    """change_configuration és get_ws helyett: naplózza a hívásokat."""
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []
        self.online: set[str] = set()
        self.reply: dict = {"status": "Accepted"}

    async def change_configuration(self, cp_id, key, value):
        self.calls.append((cp_id, key, value))
        return self.reply

    async def get_ws(self, cp_id):
        return object() if cp_id in self.online else None


@pytest.fixture
def fake(monkeypatch):
    f = _Fake()
    monkeypatch.setattr(registry, "change_configuration", f.change_configuration)
    monkeypatch.setattr(registry, "get_ws", f.get_ws)
    lb.reset_state()
    yield f
    lb.reset_state()


async def _seed(group="var", max_a=32):
    async with TestSession() as s:
        a = ChargePoint(ocpp_id="var_1", status="available", last_seen_at=utcnow(), is_published=True,
                        load_group=group, load_group_max_a=max_a, max_current_a=32)
        b = ChargePoint(ocpp_id="var_2", status="available", last_seen_at=utcnow(), is_published=True,
                        load_group=group, load_group_max_a=max_a, max_current_a=32)
        s.add_all([a, b])
        await s.commit()
        return a.id, b.id


async def _open_session(cp_id, tx="TX1", started=True):
    async with TestSession() as s:
        cs = ChargeSession(charge_point_id=cp_id, connector_id=1,
                           ocpp_transaction_id=(tx if started else None),
                           started_at=utcnow() - timedelta(minutes=1), anonymous_email="x@example.hu")
        s.add(cs)
        await s.commit()
        return cs.id


async def _close_session(sid):
    async with TestSession() as s:
        cs = (await s.execute(select(ChargeSession).where(ChargeSession.id == sid))).scalar_one()
        cs.finished_at = utcnow()
        await s.commit()


@pytest.mark.asyncio
async def test_rebalance_flow(client, fake):
    a_id, b_id = await _seed()
    fake.online = {"var_1", "var_2"}

    # 1) senki nem tölt → 32/32, mindkettőnek kimegy
    t = await lb.rebalance_group("var", "t")
    assert t == {"var_1": 32, "var_2": 32}
    assert sorted(fake.calls) == [("var_1", "CurrentDynamic", "32"), ("var_2", "CurrentDynamic", "32")]

    # 2) ugyanaz újra → nincs új küldés (csak változásnál)
    fake.calls.clear()
    await lb.rebalance_group("var", "t")
    assert fake.calls == []

    # 3) var_1 tölt → var_1 marad 32 (nincs küldés), var_2 6
    s1 = await _open_session(a_id, "TX1")
    t = await lb.rebalance_group("var", "start var_1")
    assert t == {"var_1": 32, "var_2": 6}
    assert fake.calls == [("var_2", "CurrentDynamic", "6")]

    # 4) var_2 is tölt → 16/16
    fake.calls.clear()
    s2 = await _open_session(b_id, "TX2")
    t = await lb.rebalance_group("var", "start var_2")
    assert t == {"var_1": 16, "var_2": 16}
    assert sorted(fake.calls) == [("var_1", "CurrentDynamic", "16"), ("var_2", "CurrentDynamic", "16")]

    # 5) var_1 leáll → var_2 32, var_1 6
    fake.calls.clear()
    await _close_session(s1)
    t = await lb.rebalance_group("var", "stop var_1")
    assert t == {"var_1": 6, "var_2": 32}

    # 6) var_2 is leáll → 32/32
    await _close_session(s2)
    t = await lb.rebalance_group("var", "stop var_2")
    assert t == {"var_1": 32, "var_2": 32}

    snap = lb.snapshot()
    assert snap["var_1"]["applied_a"] == 32 and snap["var_1"]["active"] is False


@pytest.mark.asyncio
async def test_waiting_session_is_not_active(client, fake):
    # nyitott session, de még nincs StartTransaction (ocpp_transaction_id None) → nem tölt
    a_id, b_id = await _seed()
    fake.online = {"var_1", "var_2"}
    await _open_session(a_id, started=False)
    t = await lb.rebalance_group("var", "t")
    assert t == {"var_1": 32, "var_2": 32}


@pytest.mark.asyncio
async def test_offline_member_skipped_and_reapplied_on_boot(client, fake):
    a_id, b_id = await _seed()
    fake.online = {"var_1"}
    await lb.rebalance_group("var", "t")
    assert fake.calls == [("var_1", "CurrentDynamic", "32")]
    assert lb.snapshot()["var_2"]["applied_a"] is None and lb.snapshot()["var_2"]["online"] is False
    # var_2 feljön (boot) → most kapja meg
    fake.calls.clear()
    fake.online = {"var_1", "var_2"}
    await lb.rebalance_for_cp("var_2", "boot")
    assert fake.calls == [("var_2", "CurrentDynamic", "32")]


@pytest.mark.asyncio
async def test_rejected_reply_is_recorded_and_retried(client, fake):
    await _seed()
    fake.online = {"var_1", "var_2"}
    fake.reply = {"status": "Rejected"}
    await lb.rebalance_group("var", "t")
    st = lb.snapshot()["var_1"]
    assert st["applied_a"] is None and "Rejected" in (st["last_error"] or "")
    # következő körben újra próbálja
    fake.calls.clear()
    fake.reply = {"status": "Accepted"}
    await lb.rebalance_group("var", "t")
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_group_without_limit_does_nothing(client, fake):
    await _seed(max_a=None)
    fake.online = {"var_1", "var_2"}
    assert await lb.rebalance_group("var", "t") == {}
    assert fake.calls == []


@pytest.mark.asyncio
async def test_cp_without_group_noop(client, fake):
    async with TestSession() as s:
        s.add(ChargePoint(ocpp_id="solo", status="available", last_seen_at=utcnow()))
        await s.commit()
    fake.online = {"solo"}
    await lb.rebalance_for_cp("solo", "start")
    assert fake.calls == []


# ── admin API ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_config_and_load_groups(client, fake):
    a_id, b_id = await _seed(group=None, max_a=None)
    fake.online = {"var_1", "var_2"}
    for cid in (a_id, b_id):
        r = await client.put(f"/api/admin/charge-points/{cid}", headers=basic(),
                             json={"load_group": "nograd_var", "load_group_max_a": 32, "max_current_a": 32})
        assert r.status_code == 200, r.text
        assert r.json()["load_group"] == "nograd_var"
    r = await client.put(f"/api/admin/charge-points/{a_id}", headers=basic(), json={"load_group_max_a": 3})
    assert r.status_code == 422

    r = await client.post("/api/admin/load-groups/nograd_var/rebalance", headers=basic())
    assert r.status_code == 200, r.text
    assert r.json()["targets"] == {"var_1": 32, "var_2": 32}

    r = await client.get("/api/admin/load-groups", headers=basic())
    assert r.status_code == 200
    g = r.json()[0]
    assert g["name"] == "nograd_var" and g["max_a"] == 32
    assert sorted(m["ocpp_id"] for m in g["members"]) == ["var_1", "var_2"]
    assert all(m["applied_a"] == 32 for m in g["members"])

    r = await client.post("/api/admin/load-groups/nincs/rebalance", headers=basic())
    assert r.status_code == 404

    # csoport törlése → nincs elosztás
    r = await client.put(f"/api/admin/charge-points/{a_id}", headers=basic(), json={"load_group": ""})
    assert r.status_code == 200 and r.json()["load_group"] is None


# ── betáplálás-védelem: csökkentés előbb, növelés csak siker után ─────────────

@pytest.mark.asyncio
async def test_decrease_before_increase_and_abort_on_failure(client, fake):
    a_id, b_id = await _seed()
    fake.online = {"var_1", "var_2"}
    s1 = await _open_session(a_id, "TX1")
    await lb.rebalance_group("var", "t")           # var_1 32, var_2 6
    fake.calls.clear()

    # var_1 leáll, var_2 indul: var_1 32→6 (csökkentés), var_2 6→32 (növelés) – ebben a sorrendben
    await _close_session(s1)
    await _open_session(b_id, "TX2")
    await lb.rebalance_group("var", "t")
    assert fake.calls == [("var_1", "CurrentDynamic", "6"), ("var_2", "CurrentDynamic", "32")]

    # ha a csökkentés elbukik, a növelés NEM megy ki (a betáplálás nem lóghat túl)
    fake.calls.clear()
    fake.reply = {"status": "Rejected"}
    await _open_session(a_id, "TX3")               # mindkettő tölt → 16/16: var_2 32→16 csökkentés, var_1 6→16 növelés
    await lb.rebalance_group("var", "t")
    assert fake.calls == [("var_2", "CurrentDynamic", "16")]
    st = lb.snapshot()
    assert st["var_2"]["applied_a"] is None and st["var_1"]["applied_a"] == 6

    # következő kör (periodic) sikerrel: mindkettő 16
    fake.calls.clear()
    fake.reply = {"status": "Accepted"}
    await lb.rebalance_group("var", "periodic")
    assert sorted(fake.calls) == [("var_1", "CurrentDynamic", "16"), ("var_2", "CurrentDynamic", "16")]


# ── ügyfél-tájékoztatás ───────────────────────────────────────────────────────

def test_kw_for_amps():
    assert lb.kw_for_amps(32) == 22
    assert lb.kw_for_amps(16) == 11
    assert lb.kw_for_amps(10) == 7
    assert lb.kw_for_amps(6) == 4


@pytest.mark.asyncio
async def test_public_charge_points_and_session_expose_sharing(client, fake):
    a_id, b_id = await _seed()
    fake.online = {"var_1", "var_2"}
    async with TestSession() as s:
        s.add(ChargePoint(ocpp_id="solo", status="available", last_seen_at=utcnow(), is_published=True))
        await s.commit()

    r = await client.get("/api/charge-points/")
    assert r.status_code == 200
    by = {c["ocpp_id"]: c for c in r.json()}
    assert by["solo"]["load_sharing"] is None
    ls = by["var_1"]["load_sharing"]
    assert ls["members"] == 2 and ls["group_max_kw"] == 22 and ls["shared_kw"] == 11
    assert ls["current_limit_kw"] is None      # még nem futott kiosztás

    # var_2 tölt → var_1 kártyáján: most 4 kW-ra korlátozva (6 A), shared_now
    s2 = await _open_session(b_id, "TX2")
    await lb.rebalance_group("var", "t")
    r = await client.get(f"/api/charge-points/{a_id}")
    ls = r.json()["load_sharing"]
    assert ls["current_limit_kw"] == 4 and ls["shared_now"] is True
    r = await client.get(f"/api/charge-points/{b_id}")
    ls = r.json()["load_sharing"]
    assert ls["current_limit_kw"] == 22 and ls["shared_now"] is False

    # mindkettő tölt → a var_2 sessionje: power_limit 11 kW, shared_now
    s1 = await _open_session(a_id, "TX1")
    await lb.rebalance_group("var", "t")
    r = await client.get(f"/api/sessions/{s2}")
    assert r.status_code == 200
    pl = r.json()["power_limit"]
    assert pl == {"limit_a": 16, "limit_kw": 11, "cap_kw": 22, "shared_now": True}

    # var_1 leáll → var_2 újra 22, nem osztott
    await _close_session(s1)
    await lb.rebalance_group("var", "t")
    pl = (await client.get(f"/api/sessions/{s2}")).json()["power_limit"]
    assert pl["limit_kw"] == 22 and pl["shared_now"] is False
    # lezárt session: nincs power_limit
    await _close_session(s2)
    assert "power_limit" not in (await client.get(f"/api/sessions/{s2}")).json()
