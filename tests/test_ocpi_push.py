"""F5 tests: outbound push (CPO = Sender) to a registered partner."""
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import ChargePoint, ChargeSession, Location, OcpiParty
from app.ocpi import push
from app.ocpi.services import cdr_service, push_service
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession


@pytest.fixture
async def partner_with_endpoints():
    async with TestSession() as s:
        s.add(OcpiParty(
            role="EMSP", country_code="HU", party_id="EMS",
            token_incoming="c-in", token_outgoing="b-out", status="REGISTERED",
            endpoints=[
                {"identifier": "cdrs", "role": "RECEIVER", "url": "https://emsp.test/ocpi/2.2.1/cdrs"},
                {"identifier": "sessions", "role": "RECEIVER", "url": "https://emsp.test/ocpi/2.2.1/sessions"},
                {"identifier": "locations", "role": "RECEIVER", "url": "https://emsp.test/ocpi/2.2.1/locations"},
            ],
        ))
        await s.commit()


async def _seed_finished_session():
    async with TestSession() as s:
        loc = Location(name="loc", address_text="1051 Budapest, Tér 1.", latitude=47.5, longitude=19.0,
                       country_code="HU", party_id="ENF")
        s.add(loc)
        await s.flush()
        cp = ChargePoint(ocpp_id="PUSH-CP", location_id=loc.id, connector_type="Type 2", max_power_kw=22.0,
                         status="available", ocpi_evse_uid="PUSH-CP", last_seen_at=utcnow())
        s.add(cp)
        await s.flush()
        cs = ChargeSession(charge_point_id=cp.id, connector_id=1, ocpp_transaction_id="900",
                           started_at=utcnow() - timedelta(hours=1), finished_at=utcnow(),
                           energy_kwh=5.0, cost_huf=850.0)
        s.add(cs)
        await s.commit()
        return loc.id, cp.id, cs.id


async def test_push_cdr_posts_to_partner(partner_with_endpoints, monkeypatch):
    loc_id, cp_id, cs_id = await _seed_finished_session()
    async with TestSession() as s:
        cs = (await s.execute(
            select(ChargeSession).options(selectinload(ChargeSession.charge_point).selectinload(ChargePoint.location))
            .where(ChargeSession.id == cs_id)
        )).scalar_one()
        await cdr_service.snapshot_cdr(s, cs)

    captured = {}

    async def fake_raw_post(url, token, payload):
        captured["url"] = url
        captured["token"] = token
        captured["payload"] = payload
        return 201

    monkeypatch.setattr(push, "raw_post", fake_raw_post)
    await push_service.push_cdr(str(cs_id))

    assert captured["url"] == "https://emsp.test/ocpi/2.2.1/cdrs"
    assert captured["token"] == "b-out"
    assert captured["payload"]["id"] == str(cs_id)
    assert captured["payload"]["total_energy"] == 5.0


async def test_push_session_puts_to_partner(partner_with_endpoints, monkeypatch):
    loc_id, cp_id, cs_id = await _seed_finished_session()

    captured = {}

    async def fake_put(url, token, payload):
        captured["url"] = url
        captured["payload"] = payload
        return None

    monkeypatch.setattr(push, "put_json", fake_put)
    await push_service.push_session(cs_id)

    assert captured["url"] == f"https://emsp.test/ocpi/2.2.1/sessions/HU/ENF/{cs_id}"
    assert captured["payload"]["status"] == "COMPLETED"


async def test_push_noop_without_registered_partner(monkeypatch):
    # No partner inserted -> push should silently no-op (no exception)
    called = {"n": 0}

    async def fake_raw_post(url, token, payload):
        called["n"] += 1
        return 200

    monkeypatch.setattr(push, "raw_post", fake_raw_post)
    await push_service.push_cdr("123")
    assert called["n"] == 0
