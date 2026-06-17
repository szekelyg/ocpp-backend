"""F3 integration tests: Sessions, CDRs, Tariffs (Sender)."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import ChargePoint, ChargeSession, Location, OcpiCdr
from app.ocpi.services import cdr_service
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession, token_header


async def _seed_finished_session(*, energy=10.0, cost=1700.0):
    async with TestSession() as s:
        loc = Location(
            name="Teszt loc", address_text="1051 Budapest, Vörösmarty tér 1.",
            latitude=47.4979, longitude=19.0402,
            country_code="HU", party_id="ENF", time_zone="Europe/Budapest",
        )
        s.add(loc)
        await s.flush()
        cp = ChargePoint(ocpp_id="CPS1", location_id=loc.id, connector_type="CCS2",
                         max_power_kw=50.0, status="available", ocpi_evse_uid="CPS1",
                         last_seen_at=utcnow())
        s.add(cp)
        await s.flush()
        start = utcnow() - timedelta(hours=1)
        cs = ChargeSession(
            charge_point_id=cp.id, connector_id=1, ocpp_transaction_id="555",
            started_at=start, finished_at=utcnow(),
            meter_start_wh=0, meter_stop_wh=energy * 1000,
            energy_kwh=energy, cost_huf=cost, anonymous_email="x@y.hu",
        )
        s.add(cs)
        await s.commit()
        return loc.id, cp.id, cs.id


# --- Tariffs --------------------------------------------------------------

async def test_tariff_built_from_env(client, party_token):
    r = await client.get("/ocpi/2.2.1/tariffs", headers=token_header(party_token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    t = data[0]
    assert t["id"] == "enf-default"
    assert t["currency"] == "HUF"
    pc = t["elements"][0]["price_components"][0]
    assert pc["type"] == "ENERGY"
    assert pc["vat"] == 27.0
    assert abs(pc["price"] - 170 / 1.27) < 0.01     # net of gross 170
    assert t["min_price"]["incl_vat"] == 500.0


async def test_get_tariff_by_id_and_unknown(client, party_token):
    r = await client.get("/ocpi/2.2.1/tariffs/enf-default", headers=token_header(party_token))
    assert r.status_code == 200
    r2 = await client.get("/ocpi/2.2.1/tariffs/nope", headers=token_header(party_token))
    assert r2.status_code == 404
    assert r2.json()["status_code"] == 2003


# --- Sessions -------------------------------------------------------------

async def test_session_list_and_get(client, party_token):
    loc_id, cp_id, cs_id = await _seed_finished_session()
    r = await client.get("/ocpi/2.2.1/sessions", headers=token_header(party_token))
    assert r.status_code == 200
    assert r.headers["X-Total-Count"] == "1"
    sess = r.json()["data"][0]
    assert sess["id"] == str(cs_id)
    assert sess["status"] == "COMPLETED"
    assert sess["kwh"] == 10.0
    assert sess["currency"] == "HUF"
    assert sess["location_id"] == str(loc_id)
    assert sess["evse_uid"] == "CPS1"
    assert sess["total_cost"]["incl_vat"] == 1700.0
    assert sess["cdr_token"]["type"] == "AD_HOC_USER"

    r2 = await client.get(f"/ocpi/2.2.1/sessions/{cs_id}", headers=token_header(party_token))
    assert r2.status_code == 200
    assert r2.json()["data"]["id"] == str(cs_id)


# --- CDRs -----------------------------------------------------------------

async def test_cdr_snapshot_and_endpoints(client, party_token):
    loc_id, cp_id, cs_id = await _seed_finished_session(energy=8.0, cost=1360.0)

    # snapshot via the service (as the completion hook would)
    async with TestSession() as s:
        cs = (
            await s.execute(
                select(ChargeSession)
                .options(selectinload(ChargeSession.charge_point).selectinload(ChargePoint.location))
                .where(ChargeSession.id == cs_id)
            )
        ).scalar_one()
        row = await cdr_service.snapshot_cdr(s, cs)
        assert row is not None

    r = await client.get("/ocpi/2.2.1/cdrs", headers=token_header(party_token))
    assert r.status_code == 200
    assert r.headers["X-Total-Count"] == "1"
    cdr = r.json()["data"][0]
    assert cdr["id"] == str(cs_id)
    assert cdr["total_energy"] == 8.0
    assert cdr["total_cost"]["incl_vat"] == 1360.0
    assert cdr["currency"] == "HUF"
    assert cdr["cdr_location"]["connector_standard"] == "IEC_62196_T2_COMBO"
    assert cdr["cdr_location"]["connector_power_type"] == "DC"
    # one charging period with ENERGY + TIME dimensions
    dims = {d["type"] for d in cdr["charging_periods"][0]["dimensions"]}
    assert dims == {"ENERGY", "TIME"}
    assert cdr["tariffs"][0]["id"] == "enf-default"

    r2 = await client.get(f"/ocpi/2.2.1/cdrs/{cs_id}", headers=token_header(party_token))
    assert r2.status_code == 200
    assert r2.json()["data"]["id"] == str(cs_id)


async def test_cdr_snapshot_is_idempotent(client, party_token):
    loc_id, cp_id, cs_id = await _seed_finished_session()
    async with TestSession() as s:
        cs = (
            await s.execute(
                select(ChargeSession)
                .options(selectinload(ChargeSession.charge_point).selectinload(ChargePoint.location))
                .where(ChargeSession.id == cs_id)
            )
        ).scalar_one()
        await cdr_service.snapshot_cdr(s, cs)
        await cdr_service.snapshot_cdr(s, cs)   # second call: no duplicate

    async with TestSession() as s:
        count = (await s.execute(select(OcpiCdr))).scalars().all()
        assert len(count) == 1
