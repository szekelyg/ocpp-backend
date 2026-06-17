"""F2 integration tests: Locations (Sender)."""
from app.db.models import ChargePoint, Location
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession, token_header


async def _seed_location(*, ocpp_id="CP001", status="available", last_seen=True):
    async with TestSession() as s:
        loc = Location(
            name="Vörösmarty tér töltő",
            address_text="1051 Budapest, Vörösmarty tér 1.",
            latitude=47.4979, longitude=19.0402,
            country_code="HU", party_id="ENF", time_zone="Europe/Budapest",
        )
        s.add(loc)
        await s.flush()
        cp = ChargePoint(
            ocpp_id=ocpp_id, location_id=loc.id,
            connector_type="Type 2", max_power_kw=22.0,
            status=status, ocpi_evse_uid=ocpp_id,
            last_seen_at=utcnow() if last_seen else None,
        )
        s.add(cp)
        await s.commit()
        return loc.id, cp.id


async def test_list_locations_shape_and_pagination(client, party_token):
    loc_id, cp_id = await _seed_location()
    r = await client.get("/ocpi/2.2.1/locations", headers=token_header(party_token))
    assert r.status_code == 200, r.text
    assert r.headers["X-Total-Count"] == "1"
    assert "X-Limit" in r.headers

    data = r.json()["data"]
    assert len(data) == 1
    loc = data[0]
    assert loc["id"] == str(loc_id)
    assert loc["country_code"] == "HU" and loc["party_id"] == "ENF"
    assert loc["country"] == "HUN"
    # address parsed from the single address_text field
    assert loc["city"] == "Budapest"
    assert loc["postal_code"] == "1051"
    assert loc["address"] == "Vörösmarty tér 1."
    assert loc["coordinates"]["latitude"] == "47.497900"

    evse = loc["evses"][0]
    assert evse["evse_id"] == f"HU*ENF*E{cp_id}"
    assert evse["status"] == "AVAILABLE"
    conn = evse["connectors"][0]
    assert conn["standard"] == "IEC_62196_T2"
    assert conn["power_type"] == "AC_3_PHASE"
    assert conn["format"] == "SOCKET"
    assert conn["tariff_ids"] == ["enf-default"]


async def test_get_location_evse_connector(client, party_token):
    loc_id, cp_id = await _seed_location(ocpp_id="CP-XYZ")
    r = await client.get(f"/ocpi/2.2.1/locations/{loc_id}", headers=token_header(party_token))
    assert r.status_code == 200
    assert r.json()["data"]["id"] == str(loc_id)

    r2 = await client.get(f"/ocpi/2.2.1/locations/{loc_id}/CP-XYZ", headers=token_header(party_token))
    assert r2.status_code == 200
    assert r2.json()["data"]["uid"] == "CP-XYZ"

    r3 = await client.get(f"/ocpi/2.2.1/locations/{loc_id}/CP-XYZ/1", headers=token_header(party_token))
    assert r3.status_code == 200
    assert r3.json()["data"]["id"] == "1"


async def test_unknown_location_returns_2003(client, party_token):
    r = await client.get("/ocpi/2.2.1/locations/99999", headers=token_header(party_token))
    assert r.status_code == 404
    assert r.json()["status_code"] == 2003


async def test_locations_requires_party_token(client):
    # Token A is not enough for data modules
    r = await client.get("/ocpi/2.2.1/locations", headers=token_header("test-token-a"))
    assert r.status_code == 401


async def test_offline_charge_point_status_unknown(client, party_token):
    loc_id, cp_id = await _seed_location(ocpp_id="CP-OFF", last_seen=False)
    r = await client.get(f"/ocpi/2.2.1/locations/{loc_id}/CP-OFF", headers=token_header(party_token))
    assert r.json()["data"]["status"] == "UNKNOWN"
