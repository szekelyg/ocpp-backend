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
