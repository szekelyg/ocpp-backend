"""F4 integration tests: Tokens (Receiver) + Commands (Receiver)."""
import asyncio

import pytest

from app.db.models import ChargePoint, Location
from app.ocpi import push
from app.ocpp import registry
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession, token_header


def _token_obj(uid="RFID123"):
    return {
        "country_code": "HU", "party_id": "EMS", "uid": uid, "type": "RFID",
        "contract_id": "HU-EMS-C123", "issuer": "Test eMSP",
        "valid": True, "whitelist": "ALLOWED",
        "last_updated": "2026-06-17T10:00:00Z",
    }


# --- Tokens (Receiver) ----------------------------------------------------

async def test_put_get_patch_token(client, party_token):
    h = token_header(party_token)
    r = await client.put("/ocpi/2.2.1/tokens/HU/EMS/RFID123?type=RFID", headers=h, json=_token_obj())
    assert r.status_code == 200, r.text
    assert r.json()["status_code"] == 1000

    r2 = await client.get("/ocpi/2.2.1/tokens/HU/EMS/RFID123?type=RFID", headers=h)
    assert r2.status_code == 200
    tok = r2.json()["data"]
    assert tok["uid"] == "RFID123"
    assert tok["valid"] is True
    assert tok["whitelist"] == "ALLOWED"

    r3 = await client.patch("/ocpi/2.2.1/tokens/HU/EMS/RFID123?type=RFID", headers=h, json={"valid": False})
    assert r3.status_code == 200
    r4 = await client.get("/ocpi/2.2.1/tokens/HU/EMS/RFID123?type=RFID", headers=h)
    assert r4.json()["data"]["valid"] is False


async def test_get_unknown_token(client, party_token):
    r = await client.get("/ocpi/2.2.1/tokens/HU/EMS/NOPE?type=RFID", headers=token_header(party_token))
    assert r.status_code == 404
    assert r.json()["status_code"] == 2003


async def test_patch_unknown_token(client, party_token):
    r = await client.patch("/ocpi/2.2.1/tokens/HU/EMS/NOPE?type=RFID", headers=token_header(party_token), json={"valid": False})
    assert r.status_code == 404


# --- Commands (Receiver) --------------------------------------------------

async def _seed_cp(ocpp_id="CMD-CP"):
    async with TestSession() as s:
        loc = Location(name="loc", address_text="1051 Budapest, Tér 1.",
                       latitude=47.5, longitude=19.0, country_code="HU", party_id="ENF")
        s.add(loc)
        await s.flush()
        cp = ChargePoint(ocpp_id=ocpp_id, location_id=loc.id, connector_type="Type 2",
                         max_power_kw=22.0, status="available", ocpi_evse_uid=ocpp_id,
                         last_seen_at=utcnow())
        s.add(cp)
        await s.commit()
        return loc.id, cp.id


@pytest.fixture
def capture_ocpp(monkeypatch):
    calls = {}

    async def fake_start(cp_id, connector_id, id_tag):
        calls["start"] = (cp_id, connector_id, id_tag)
        return {"status": "Accepted"}

    async def fake_stop(cp_id, transaction_id):
        calls["stop"] = (cp_id, transaction_id)
        return {"status": "Accepted"}

    async def fake_call(cp_id, action, payload, timeout_s=12.0):
        calls["call"] = (cp_id, action, payload)
        return {"status": "Accepted"}

    async def fake_raw_post(url, token, payload):
        calls.setdefault("callbacks", []).append((url, token, payload))
        return 200

    monkeypatch.setattr(registry, "remote_start_transaction", fake_start)
    monkeypatch.setattr(registry, "remote_stop_transaction", fake_stop)
    monkeypatch.setattr(registry, "send_call_and_wait", fake_call)
    monkeypatch.setattr(push, "raw_post", fake_raw_post)
    return calls


async def test_start_session_accepted_and_callback(client, party_token, capture_ocpp):
    loc_id, cp_id = await _seed_cp("START-CP")
    body = {
        "response_url": "https://emsp.test/commands/START_SESSION/42",
        "token": _token_obj(uid="DRIVER1"),
        "location_id": str(loc_id),
        "evse_uid": "START-CP",
        "connector_id": "1",
    }
    r = await client.post("/ocpi/2.2.1/commands/START_SESSION", headers=token_header(party_token), json=body)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["result"] == "ACCEPTED"

    await asyncio.sleep(0.05)  # let the background task run (if not already)
    assert capture_ocpp["start"] == ("START-CP", 1, "DRIVER1")
    cb = capture_ocpp["callbacks"][0]
    assert cb[0] == body["response_url"]
    assert cb[2] == {"result": "ACCEPTED"}


async def test_stop_unknown_session(client, party_token, capture_ocpp):
    body = {"response_url": "https://emsp.test/cb", "session_id": "999999"}
    r = await client.post("/ocpi/2.2.1/commands/STOP_SESSION", headers=token_header(party_token), json=body)
    assert r.status_code == 200
    assert r.json()["data"]["result"] == "UNKNOWN_SESSION"
    await asyncio.sleep(0.02)
    assert "stop" not in capture_ocpp  # no OCPP call for unknown session


async def test_unlock_connector(client, party_token, capture_ocpp):
    loc_id, cp_id = await _seed_cp("UNLOCK-CP")
    body = {
        "response_url": "https://emsp.test/cb",
        "location_id": str(loc_id),
        "evse_uid": "UNLOCK-CP",
        "connector_id": "1",
    }
    r = await client.post("/ocpi/2.2.1/commands/UNLOCK_CONNECTOR", headers=token_header(party_token), json=body)
    assert r.json()["data"]["result"] == "ACCEPTED"
    await asyncio.sleep(0.05)
    assert capture_ocpp["call"][0] == "UNLOCK-CP"
    assert capture_ocpp["call"][1] == "UnlockConnector"
    assert capture_ocpp["call"][2] == {"connectorId": 1}


async def test_unknown_command_not_supported(client, party_token):
    r = await client.post("/ocpi/2.2.1/commands/FOO", headers=token_header(party_token), json={})
    assert r.status_code == 200
    assert r.json()["data"]["result"] == "NOT_SUPPORTED"
