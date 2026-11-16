"""Biztonsági javítások a 2026-11-es átvilágítás után (a test_biztonsag.py folytatása)."""
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.test_biztonsag import ADMIN_AUTH, BILLING, FakeWS, _cp  # noqa: F401  (közös segédek + teszt-env)


# ── 1. OCPP: azonosító nélküli útvonal nincs ─────────────────────────────────

def test_ocpp_azonosito_nelkuli_utvonal_elutasitva():
    """A /ocpp-n a BootNotification sorozatszáma döntötte el, kinek a nevében beszél a kapcsolat –
    hitelesítés és duplikált-kapcsolat szabály nélkül felülírta egy élő töltő registry-bejegyzését."""
    from app.main import app

    for path in ("/ocpp", "/ocpp/"):
        with pytest.raises(WebSocketDisconnect):
            with TestClient(app).websocket_connect(path):
                pass


# ── 2. OCPP: erőforrás-kimerítés (óriás keret, napló, töltő-felvétel) ─────────

async def test_ocpp_nyers_keret_csonkolva_kerul_a_naploba(caplog):
    import logging
    from app.ocpp import ws as ws_mod

    huge = "[" + "9" * 50_000          # nem JSON → a ciklus eldobja, de előtte naplózná
    with caplog.at_level(logging.DEBUG, logger="ocpp"):
        await ws_mod.handle_ocpp(FakeWS(messages=[huge]), "RAW-1")
    raw = [r.getMessage() for r in caplog.records if r.getMessage().startswith("OCPP RAW")]
    assert len(raw) == 1 and len(raw[0]) <= ws_mod.RAW_LOG_MAX_CHARS + 20


async def test_boot_ismeretlen_toltok_szama_korlatos(monkeypatch):
    """Ismeretlen azonosítójú BootNotification korlátlanul hozott létre charge_points sort."""
    import json
    from sqlalchemy import func, select
    from app.db.models import ChargePoint
    from app.ocpp.handlers import boot
    from app.ocpp.ws import handle_ocpp
    from tests.conftest import TestSession

    monkeypatch.setattr(boot, "AsyncSessionLocal", TestSession)
    monkeypatch.setattr(boot, "MAX_UNPUBLISHED_CHARGE_POINTS", 2)
    await _cp("BOOT-ISMERT")                                   # publikált: nem számít a keretbe
    boot_msg = json.dumps([2, "1", "BootNotification", {"chargePointVendor": "X", "chargePointModel": "Y"}])

    async def _boot(cp_id):
        ws = FakeWS(messages=[boot_msg])
        await handle_ocpp(ws, cp_id)
        return json.loads(ws.sent[0])[2]["status"]

    assert await _boot("UJ-1") == "Accepted"
    assert await _boot("UJ-2") == "Accepted"
    assert await _boot("UJ-3") == "Rejected"                   # a keret betelt: nem vesszük fel
    assert await _boot("UJ-1") == "Accepted"                   # a már felvett és
    assert await _boot("BOOT-ISMERT") == "Accepted"            # az ismert töltő bootja megy tovább
    async with TestSession() as s:
        assert (await s.execute(select(func.count()).select_from(ChargePoint))).scalar_one() == 3


def test_uvicorn_keretmeret_es_naplomeret_korlat():
    from pathlib import Path

    deploy = Path(__file__).resolve().parent.parent / "deploy"
    assert "--ws-max-size 65536" in (deploy / "entrypoint.sh").read_text()
    compose = (deploy / "docker-compose.hetzner.yml").read_text()
    assert 'max-size: "50m"' in compose and compose.count("logging: *logging") == 3
