"""F1 integration tests: Versions + Credentials handshake."""
import pytest
from sqlalchemy import select

from app.ocpi import push
from app.db.models import OcpiParty
from tests.conftest import TestSession, token_header

TOKEN_A = "test-token-a"


# --- Versions -------------------------------------------------------------

async def test_versions_requires_token(client):
    r = await client.get("/ocpi/versions")
    assert r.status_code == 401
    assert r.json()["status_code"] == 2000


async def test_versions_with_token_a(client):
    r = await client.get("/ocpi/versions", headers=token_header(TOKEN_A))
    assert r.status_code == 200
    body = r.json()
    assert body["status_code"] == 1000
    versions = body["data"]
    assert any(v["version"] == "2.2.1" for v in versions)
    assert versions[0]["url"].endswith("/ocpi/2.2.1")


async def test_version_details_lists_modules(client):
    r = await client.get("/ocpi/2.2.1", headers=token_header(TOKEN_A))
    assert r.status_code == 200
    data = r.json()["data"]
    ids = {(e["identifier"], e["role"]) for e in data["endpoints"]}
    assert ("locations", "SENDER") in ids
    assert ("tokens", "RECEIVER") in ids
    assert ("commands", "RECEIVER") in ids
    assert ("credentials", "SENDER") in ids


async def test_bad_token_rejected(client):
    r = await client.get("/ocpi/versions", headers=token_header("wrong"))
    assert r.status_code == 401


async def test_disabled_ocpi_is_fail_closed(client, monkeypatch):
    # Production default OCPI_ENABLED=false -> every protected endpoint returns 503
    from app.ocpi import config
    monkeypatch.setattr(config, "ocpi_enabled", lambda: False)
    r = await client.get("/ocpi/versions", headers=token_header(TOKEN_A))
    assert r.status_code == 503
    assert r.json()["status_code"] == 3000


# --- Credentials handshake ------------------------------------------------

@pytest.fixture
def mock_partner(monkeypatch):
    """Stub the outbound calls registration makes to the partner."""
    async def fake_get_json(url, token):
        if url.endswith("/versions"):
            return [{"version": "2.2.1", "url": "https://emsp.test/ocpi/2.2.1"}]
        return {"version": "2.2.1", "endpoints": [
            {"identifier": "credentials", "role": "RECEIVER", "url": "https://emsp.test/ocpi/2.2.1/credentials"},
            {"identifier": "locations", "role": "RECEIVER", "url": "https://emsp.test/ocpi/2.2.1/locations"},
        ]}
    monkeypatch.setattr(push, "get_json", fake_get_json)


def _partner_credentials():
    return {
        "token": "token-b-from-emsp",
        "url": "https://emsp.test/ocpi/versions",
        "roles": [{
            "role": "EMSP",
            "party_id": "EMS",
            "country_code": "HU",
            "business_details": {"name": "Test eMSP"},
        }],
    }


async def test_registration_creates_party_and_returns_token_c(client, mock_partner):
    r = await client.post(
        "/ocpi/2.2.1/credentials",
        headers=token_header(TOKEN_A),
        json=_partner_credentials(),
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    token_c = data["token"]
    assert token_c and token_c != TOKEN_A
    assert data["roles"][0]["role"] == "CPO"
    assert data["roles"][0]["party_id"] == "ENF"

    async with TestSession() as s:
        party = (await s.execute(select(OcpiParty))).scalar_one()
        assert party.status == "REGISTERED"
        assert party.country_code == "HU" and party.party_id == "EMS"
        assert party.token_outgoing == "token-b-from-emsp"
        assert party.token_incoming == token_c


async def test_token_c_then_authorizes_module_access(client, mock_partner):
    # register
    r = await client.post(
        "/ocpi/2.2.1/credentials",
        headers=token_header(TOKEN_A),
        json=_partner_credentials(),
    )
    token_c = r.json()["data"]["token"]
    # Token C now works on versions
    r2 = await client.get("/ocpi/versions", headers=token_header(token_c))
    assert r2.status_code == 200
    # GET credentials returns our creds carrying that party's token
    r3 = await client.get("/ocpi/2.2.1/credentials", headers=token_header(token_c))
    assert r3.status_code == 200
    assert r3.json()["data"]["token"] == token_c


async def test_double_registration_rejected(client, mock_partner):
    payload = _partner_credentials()
    await client.post("/ocpi/2.2.1/credentials", headers=token_header(TOKEN_A), json=payload)
    r = await client.post("/ocpi/2.2.1/credentials", headers=token_header(TOKEN_A), json=payload)
    assert r.status_code == 405
    assert r.json()["status_code"] == 2002
