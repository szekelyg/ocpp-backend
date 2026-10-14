"""Töltő publikálási folyamat: felcsatlakozás → admin konfigurálás → éles megjelenés.

Egy BootNotificationből felbukkanó töltő publikálatlan, tehát se a publikus API-n,
se az OCPI-ban nem látszik, és nem lehet rá fizetést indítani. Publikálni csak
hiánytalan konfigurációval lehet.
"""
import base64
import os

os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ["ADMIN_PASSWORD"] = "test-admin-pw"

import pytest
from sqlalchemy import select

from app.db.models import ChargePoint, ChargeSession, ChargingIntent, Location
from app.ocpp.handlers.boot import upsert_charge_point_from_boot
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession, token_header

# A handlerek import-időben kötik az AsyncSessionLocal-t → a teszt DB-re irányítjuk.
import app.ocpp.handlers.boot as _boot_mod
_boot_mod.AsyncSessionLocal = TestSession


ADMIN_AUTH = {
    "Authorization": "Basic " + base64.b64encode(b"admin:test-admin-pw").decode()
}


async def _seed_cp(ocpp_id="CP-PUB", published=False, with_location=True, **kw):
    async with TestSession() as s:
        loc_id = None
        if with_location:
            loc = Location(
                name="Teszt helyszín", address_text="1051 Budapest, Tér 1.",
                latitude=47.5, longitude=19.0, country_code="HU", party_id="ENF",
            )
            s.add(loc)
            await s.flush()
            loc_id = loc.id
        cp = ChargePoint(
            ocpp_id=ocpp_id, location_id=loc_id,
            connector_type=kw.get("connector_type", "Type 2"),
            max_power_kw=kw.get("max_power_kw", 22.0),
            status="available", last_seen_at=utcnow(),
            is_published=published,
        )
        s.add(cp)
        await s.commit()
        return cp.id, loc_id


# ── Boot ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_boot_creates_unpublished_charge_point():
    await upsert_charge_point_from_boot("CP-FRESH", {
        "chargePointVendor": "Volite", "chargePointModel": "V1",
        "chargePointSerialNumber": "SN1", "firmwareVersion": "1.0",
    })
    async with TestSession() as s:
        cp = (await s.execute(
            select(ChargePoint).where(ChargePoint.ocpp_id == "CP-FRESH")
        )).scalar_one()
        assert cp.is_published is False
        assert cp.location_id is None


@pytest.mark.asyncio
async def test_boot_does_not_unpublish_existing(client):
    cp_id, _ = await _seed_cp("CP-LIVE", published=True)
    await upsert_charge_point_from_boot("CP-LIVE", {"chargePointVendor": "Volite"})
    async with TestSession() as s:
        cp = (await s.execute(select(ChargePoint).where(ChargePoint.id == cp_id))).scalar_one()
        assert cp.is_published is True, "egy újraindulás nem veheti le az éles töltőt"


# ── Publikus felület ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_public_list_hides_unpublished(client):
    pub_id, _ = await _seed_cp("CP-SHOWN", published=True)
    hid_id, _ = await _seed_cp("CP-HIDDEN", published=False)

    async with TestSession() as s:
        pub_pid = (await s.execute(select(ChargePoint.public_id).where(ChargePoint.id == pub_id))).scalar_one()
        hid_pid = (await s.execute(select(ChargePoint.public_id).where(ChargePoint.id == hid_id))).scalar_one()

    r = await client.get("/api/charge-points/")
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert pub_pid in ids
    assert hid_pid not in ids

    # publikus id, régi sorszámos id és ocpp_id alapján sem érhető el a publikálatlan
    for ref in (hid_pid, hid_id, "CP-HIDDEN"):
        assert (await client.get(f"/api/charge-points/{ref}")).status_code == 404
    assert (await client.get(f"/api/charge-points/{pub_pid}")).status_code == 200


@pytest.mark.asyncio
async def test_intent_rejected_on_unpublished(client):
    cp_id, _ = await _seed_cp("CP-NOPAY", published=False)
    r = await client.post("/api/intents/", json={
        "charge_point_id": cp_id, "connector_id": 1, "email": "a@b.hu",
        "hold_amount_huf": 5000, "billing_type": "personal", "billing_name": "Teszt Elek",
        "billing_street": "Fő u. 1.", "billing_zip": "1051", "billing_city": "Budapest",
        "billing_country": "HU",
    })
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_intent_rejected_when_offline(client):
    """A nyers cp.status "available" lehet, miközben a töltő már rég nem jelentkezett."""
    async with TestSession() as s:
        loc = Location(name="L", latitude=47.5, longitude=19.0)
        s.add(loc)
        await s.flush()
        from datetime import timedelta
        cp = ChargePoint(
            ocpp_id="CP-OFFLINE", location_id=loc.id, connector_type="Type 2",
            max_power_kw=22.0, status="available", is_published=True,
            last_seen_at=utcnow() - timedelta(minutes=30),
        )
        s.add(cp)
        await s.commit()
        cp_id = cp.id

    r = await client.post("/api/intents/", json={
        "charge_point_id": cp_id, "connector_id": 1, "email": "a@b.hu",
        "hold_amount_huf": 5000, "billing_type": "personal", "billing_name": "Teszt Elek",
        "billing_street": "Fő u. 1.", "billing_zip": "1051", "billing_city": "Budapest",
        "billing_country": "HU",
    })
    assert r.status_code == 409
    assert r.json()["detail"]["status"] == "offline"


# ── Admin konfigurálás ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_admin_requires_auth(client):
    cp_id, _ = await _seed_cp("CP-AUTH")
    assert (await client.put(f"/api/admin/charge-points/{cp_id}", json={})).status_code == 401
    assert (await client.post("/api/sessions/start", json={
        "charge_point_id": cp_id, "connector_id": 1, "user_tag": "ANON",
    })).status_code == 401


@pytest.mark.asyncio
async def test_publish_blocked_until_complete(client):
    cp_id, _ = await _seed_cp("CP-INCOMPLETE", with_location=False,
                              connector_type=None, max_power_kw=None)

    r = await client.put(f"/api/admin/charge-points/{cp_id}",
                         json={"is_published": True}, headers=ADMIN_AUTH)
    assert r.status_code == 409
    missing = set(r.json()["detail"]["missing_fields"])
    assert {"location", "connector_type", "max_power_kw"} <= missing

    # A töltő továbbra sem látszik kint
    assert (await client.get("/api/charge-points/")).json() == []


class _FakeCharger:
    """A töltő OCPP-oldala: online-e, és mit válaszol az AuthorizationKey-re."""
    def __init__(self, monkeypatch, online=True, status="Accepted"):
        import app.ocpp.registry as reg
        self.calls = []

        async def get_ws(cp_id):
            return object() if online else None

        async def change_configuration(cp_id, key, value):
            self.calls.append(("ChangeConfiguration", cp_id, key, value))
            return {"status": status}

        async def send_call_and_wait(cp_id, action, payload, timeout_s=12.0):
            self.calls.append((action, cp_id, payload))
            return {"status": "Accepted"}

        monkeypatch.setattr(reg, "get_ws", get_ws)
        monkeypatch.setattr(reg, "change_configuration", change_configuration)
        monkeypatch.setattr(reg, "send_call_and_wait", send_call_and_wait)


async def _key_hash(cp_id):
    async with TestSession() as s:
        return (await s.execute(select(ChargePoint.ocpp_auth_key_hash).where(ChargePoint.id == cp_id))).scalar_one()


@pytest.mark.asyncio
async def test_publish_sets_ocpp_key_and_resets(client, monkeypatch):
    import asyncio
    from app.ocpp import auth as ocpp_auth
    charger = _FakeCharger(monkeypatch)
    cp_id, _ = await _seed_cp("CP-KEY")

    r = await client.put(f"/api/admin/charge-points/{cp_id}", json={"is_published": True}, headers=ADMIN_AUTH)
    assert r.status_code == 200, r.text
    assert r.json()["ocpp_auth_key_set"] is True and r.json()["is_published"] is True
    await asyncio.sleep(0.05)  # a Soft reset háttérben megy

    (_, _, key_name, key), (action, _, payload) = charger.calls
    assert key_name == "AuthorizationKey" and len(key) == 32
    assert action == "Reset" and payload == {"type": "Soft"}
    assert ocpp_auth.verify_password(key.encode(), await _key_hash(cp_id))
    assert key not in r.text                     # a kulcs nem megy ki az admin válaszban sem


@pytest.mark.asyncio
async def test_publish_keeps_existing_key(client, monkeypatch):
    charger = _FakeCharger(monkeypatch)
    cp_id, _ = await _seed_cp("CP-HASKEY")
    async with TestSession() as s:
        cp = await s.get(ChargePoint, cp_id)
        cp.ocpp_auth_key_hash = "meglevo"
        await s.commit()
    r = await client.put(f"/api/admin/charge-points/{cp_id}", json={"is_published": True}, headers=ADMIN_AUTH)
    assert r.status_code == 200 and r.json()["ocpp_auth_key_set"] is False
    assert charger.calls == [] and await _key_hash(cp_id) == "meglevo"


@pytest.mark.asyncio
@pytest.mark.parametrize("online,status,code,error", [
    (False, "Accepted", 409, "charger_offline"),
    (True, "Rejected", 502, "auth_key_rejected"),
])
async def test_publish_blocked_without_key(client, monkeypatch, online, status, code, error):
    _FakeCharger(monkeypatch, online=online, status=status)
    cp_id, _ = await _seed_cp(f"CP-NOKEY-{code}")
    r = await client.put(f"/api/admin/charge-points/{cp_id}", json={"is_published": True}, headers=ADMIN_AUTH)
    assert r.status_code == code and r.json()["detail"]["error"] == error
    assert await _key_hash(cp_id) is None
    assert (await client.get("/api/charge-points/")).json() == []


@pytest.mark.asyncio
async def test_configure_then_publish(client, monkeypatch):
    _FakeCharger(monkeypatch)
    cp_id, _ = await _seed_cp("CP-CONFIG", with_location=False,
                              connector_type=None, max_power_kw=None)

    r = await client.put(f"/api/admin/charge-points/{cp_id}", headers=ADMIN_AUTH, json={
        "location_name": "Vörösmarty tér – bal oszlop",
        "address_text": "1051 Budapest, Vörösmarty tér 1.",
        "latitude": 47.4979, "longitude": 19.0402,
        "connector_type": "CCS2", "max_power_kw": 50.0,
        "is_published": True,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_published"] is True
    assert body["missing_fields"] == []

    listed = (await client.get("/api/charge-points/")).json()
    row = [c for c in listed if c["id"] == body["public_id"]]
    assert len(row) == 1
    assert row[0]["location_name"] == "Vörösmarty tér – bal oszlop"
    assert row[0]["latitude"] == pytest.approx(47.4979)
    assert row[0]["connector_type"] == "CCS2"
    assert row[0]["max_power_kw"] == 50.0


@pytest.mark.asyncio
async def test_unpublish_hides_again(client):
    cp_id, _ = await _seed_cp("CP-REVOKE", published=True)
    r = await client.put(f"/api/admin/charge-points/{cp_id}",
                         json={"is_published": False}, headers=ADMIN_AUTH)
    assert r.status_code == 200
    assert r.json()["public_id"] not in [c["id"] for c in (await client.get("/api/charge-points/")).json()]


@pytest.mark.asyncio
async def test_shared_location_is_not_mutated(client):
    """Két töltő egy Location soron: a másodikat szerkesztve az első ne mozduljon el."""
    cp1_id, loc_id = await _seed_cp("CP-PILLAR-A", published=True)
    async with TestSession() as s:
        cp2 = ChargePoint(ocpp_id="CP-PILLAR-B", location_id=loc_id, connector_type="Type 2",
                          max_power_kw=22.0, status="available", last_seen_at=utcnow())
        s.add(cp2)
        await s.commit()
        cp2_id = cp2.id

    r = await client.put(f"/api/admin/charge-points/{cp2_id}", headers=ADMIN_AUTH, json={
        "location_name": "Jobb oszlop", "latitude": 47.6, "longitude": 19.1,
    })
    assert r.status_code == 200

    async with TestSession() as s:
        cp1 = (await s.execute(select(ChargePoint).where(ChargePoint.id == cp1_id))).scalar_one()
        cp2 = (await s.execute(select(ChargePoint).where(ChargePoint.id == cp2_id))).scalar_one()
        assert cp1.location_id != cp2.location_id, "a második töltő saját Location sort kapott"
        loc1 = (await s.execute(select(Location).where(Location.id == cp1.location_id))).scalar_one()
        assert loc1.latitude == 47.5 and loc1.name == "Teszt helyszín"


@pytest.mark.asyncio
async def test_delete_only_without_history(client):
    cp_id, _ = await _seed_cp("CP-TYPO")
    async with TestSession() as s:
        s.add(ChargeSession(charge_point_id=cp_id, connector_id=1, started_at=utcnow()))
        await s.commit()

    r = await client.delete(f"/api/admin/charge-points/{cp_id}", headers=ADMIN_AUTH)
    assert r.status_code == 409
    assert r.json()["detail"]["sessions"] == 1

    clean_id, _ = await _seed_cp("CP-TYPO-2")
    r = await client.delete(f"/api/admin/charge-points/{clean_id}", headers=ADMIN_AUTH)
    assert r.status_code == 200
    async with TestSession() as s:
        assert (await s.execute(
            select(ChargePoint).where(ChargePoint.id == clean_id)
        )).scalar_one_or_none() is None


# ── OCPI ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ocpi_excludes_unpublished(client, party_token):
    hidden_id, hidden_loc = await _seed_cp("CP-OCPI-HIDDEN", published=False)
    shown_id, shown_loc = await _seed_cp("CP-OCPI-SHOWN", published=True)

    r = await client.get("/ocpi/2.2.1/locations", headers=token_header(party_token))
    assert r.status_code == 200
    loc_ids = [loc["id"] for loc in r.json()["data"]]
    assert str(shown_loc) in loc_ids
    assert str(hidden_loc) not in loc_ids

    r = await client.get(f"/ocpi/2.2.1/locations/{hidden_loc}", headers=token_header(party_token))
    assert r.status_code == 404
