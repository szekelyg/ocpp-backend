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


# ── 3. Vész-Basic admin: hibás jelszavak IP-nkénti korlátja ───────────────────

def _basic_admin(password):
    import base64
    return {"Authorization": "Basic " + base64.b64encode(f"admin:{password}".encode()).decode()}


async def test_admin_basic_hibas_jelszo_korlat(client, monkeypatch):
    """Az ADMIN_PASSWORD korlátlanul próbálgatható volt (az /api/admin/* és a session-nézet admin-ágán is)."""
    from app.core import rate_limit

    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    rate_limit.STORE.clear()
    ip = {"CF-Connecting-IP": "203.0.113.50"}
    limit = rate_limit.ADMIN_BASIC_FAIL.limit
    try:
        # a jó jelszavas kérések nem fogyasztják a keretet
        for _ in range(limit + 5):
            assert (await client.get("/api/admin/charge-points", headers={**ip, **ADMIN_AUTH})).status_code == 200
        # hibás jelszó: a keretig 401 – az /api/admin/* és a session-nézet admin-ága KÖZÖS kereten
        for i in range(limit):
            path = "/api/admin/charge-points" if i % 2 else "/api/sessions/999"
            r = await client.get(path, headers={**ip, **_basic_admin(f"tipp-{i}")})
            assert r.status_code == (401 if i % 2 else 403), (i, r.text)
        r = await client.get("/api/admin/charge-points", headers={**ip, **_basic_admin("tipp")})
        assert r.status_code == 429 and r.headers.get("retry-after")
        # a keret felett a JÓ jelszó sem megy át (különben a találat a 429 mögül is kiderülne)
        assert (await client.get("/api/admin/charge-points", headers={**ip, **ADMIN_AUTH})).status_code == 429
        # a session-nézet admin-ága sem árulja el a jó jelszót (nem létező munkamenet: admin 404-et kapna)
        assert (await client.get("/api/sessions/999", headers={**ip, **ADMIN_AUTH})).status_code == 403
        # másik IP-ről az admin dolgozhat tovább
        assert (await client.get("/api/admin/charge-points",
                                 headers={"CF-Connecting-IP": "203.0.113.51", **ADMIN_AUTH})).status_code == 200
    finally:
        rate_limit.STORE.clear()


# ── 4. Intent-token aláíró titka: figyelmeztetés, ha a Stripe-titokra esik vissza ──

@pytest.mark.parametrize("auth_secret, warns", [(None, True), ("sajat-titok", False)])
async def test_indulaskor_figyelmeztet_ha_nincs_auth_secret(auth_secret, warns, monkeypatch, caplog):
    """(A megszűnt v1 e-mail-token elutasítását a test_sessions_auth.py / test_keycloak_auth.py fedi.)"""
    import logging
    from app.main import app, lifespan

    if auth_secret is None:
        monkeypatch.delenv("AUTH_SECRET", raising=False)
    else:
        monkeypatch.setenv("AUTH_SECRET", auth_secret)
    with caplog.at_level(logging.WARNING, logger="backend"):
        async with lifespan(app):
            pass
    assert any("AUTH_SECRET NINCS beállítva" in r.getMessage() for r in caplog.records) is warns


# ── 5. Számlázz.hu: a vevő adatai escape-elve kerülnek az XML-be ──────────────

async def test_szamla_xml_vevo_adatok_escape(monkeypatch):
    """A szamlazz.py nem escape-el: „Kovács & Fia" érvénytelen XML-t adott (a számla soha nem
    készült el), egy „</nev><adoszam>…" pedig felülírhatta a vevő-blokk elemeit."""
    import xml.etree.ElementTree as ET
    import szamlazz.client as szamlazz_client
    from app.services import invoice

    sent = []

    def _fake_post(url, files):
        sent.append(files["action-xmlagentxmlfile"])
        raise RuntimeError("a teszt nem megy ki a hálózatra")

    monkeypatch.setenv("SZAMLAZZ_AGENT_KEY", "teszt-kulcs")
    monkeypatch.setattr(szamlazz_client.requests, "post", _fake_post)
    name = 'Kovács & Fia "Bt." </nev><adoszam>99999999-9-99</adoszam><nev>'
    await invoice.create_session_invoice(
        session_id=1, energy_kwh=10.0, captured_huf=1700, cp_ocpp_id="CP<&>1",
        buyer_email="a&b@example.hu", buyer_name=name, buyer_zip="1051", buyer_city="Buda & Pest",
        buyer_street="Fő <u.> 1.", buyer_tax_number="<x>", billing_type="personal",
    )
    assert len(sent) == 1, "az XML érvényes, eljut a küldésig"
    ns = {"s": "http://www.szamlazz.hu/xmlszamla"}
    root = ET.fromstring(sent[0])
    vevo = root.find("s:vevo", ns)
    assert vevo.find("s:nev", ns).text == name
    assert vevo.find("s:telepules", ns).text == "Buda & Pest"
    assert vevo.find("s:cim", ns).text == "Fő <u.> 1."
    assert vevo.find("s:email", ns).text == "a&b@example.hu"
    assert [e.text for e in vevo.findall("s:adoszam", ns)] == ["<x>"]
    assert root.find("s:tetelek/s:tetel/s:megnevezes", ns).text.endswith("CP<&>1")


# ── 6. E-mailek: az ügyfél-adat HTML-escape-elve kerül a levélbe ──────────────

@pytest.fixture
def sent_emails(monkeypatch):
    from app.services import email

    sent = []

    async def _fake_send(to, subject, html):
        sent.append(html)
        return True

    monkeypatch.setattr(email, "_send", _fake_send)
    return sent


async def _helyszin(ocpp_id, name):
    """Töltő saját nevű helyszínnel (a levelek ezt mutatják a sofőrnek)."""
    from sqlalchemy import select, update
    from app.db.models import ChargePoint, Location
    from tests.conftest import TestSession

    cp_id, _ = await _cp(ocpp_id)
    async with TestSession() as s:
        loc_id = select(ChargePoint.location_id).where(ChargePoint.id == cp_id).scalar_subquery()
        await s.execute(update(Location).where(Location.id == loc_id).values(name=name))
        await s.commit()


async def test_email_ugyfel_adat_html_escape(sent_emails):
    from app.services import email

    evil = '<img src=x onerror=alert(1)> & "Fia"'
    await _helyszin("ESC-1", evil)
    await email.send_receipt_email(
        to="a@b.hu", session_id=1, cp_ocpp_id="ESC-1", energy_kwh=1.0, cost_huf=170,
        billing_name=evil, billing_type="business", billing_company=evil, billing_tax_number=evil,
        billing_street=evil, billing_zip=evil, billing_city=evil, billing_country=evil,
    )
    await email.send_charging_started_email(to="a@b.hu", session_id=1, cp_ocpp_id="ESC-1", intent_token='t"><b>')
    await email.send_no_start_email(to="a@b.hu", session_id=1, cp_ocpp_id="ESC-1")
    assert len(sent_emails) == 3
    for html in sent_emails:
        assert "<img" not in html and "<b>" not in html
        assert "&lt;img src=x" in html                    # a helyszín neve is escape-elve
    assert sent_emails[0].count("&lt;img src=x onerror=alert(1)&gt; &amp; &quot;Fia&quot;") >= 4


# ── 7. A töltő belső OCPP-azonosítója nem megy ki a sofőrnek szóló levelekben ──

async def test_email_helyszin_nev_az_ocpp_azonosito_helyett(sent_emails):
    from app.services import email

    await _helyszin("nadudvar_belso_2", "Nádudvar, SPAR parkoló")
    for cp in ("nadudvar_belso_2", "nincs_ilyen_tolto"):
        await email.send_charging_started_email(to="a@b.hu", session_id=1, cp_ocpp_id=cp)
        await email.send_no_start_email(to="a@b.hu", session_id=1, cp_ocpp_id=cp)
        await email.send_receipt_email(to="a@b.hu", session_id=1, cp_ocpp_id=cp)
    assert len(sent_emails) == 6
    for html in sent_emails:
        assert "nadudvar_belso_2" not in html and "nincs_ilyen_tolto" not in html
    for html in sent_emails[:3]:
        assert "Nádudvar, SPAR parkoló" in html


# ── 8. Biztonsági válaszfejlécek ──────────────────────────────────────────────

async def test_biztonsagi_fejlecek_minden_valaszon(client, monkeypatch):
    from app.core import rate_limit
    from app.services import keycloak

    monkeypatch.setenv("KEYCLOAK_ISSUER", "https://id.test/realms/ugyfelek")
    keycloak.reset_cache()
    # API-válasz, hibaválasz, a rate limit saját 429-e
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    rate_limit.STORE.clear()
    monkeypatch.setattr(rate_limit, "RULES", (
        rate_limit.Rule("teszt", "GET", rate_limit.re.compile(r"^/api/sessions/1$"), 1, 60),))
    paths = ("/api/charge-points/", "/api/nincs-ilyen", "/api/sessions/1", "/api/sessions/1")
    responses = [await client.get(p) for p in paths]
    assert [r.status_code for r in responses] == [200, 404, 403, 429]
    for r in responses:
        assert r.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
        assert r.headers["x-frame-options"] == "DENY"
        assert "content-security-policy" not in r.headers          # egyelőre csak Report-Only
        assert r.headers["content-security-policy-report-only"] == (
            "default-src 'self'; connect-src 'self' https://id.test; "
            "img-src 'self' data: https://*.tile.openstreetmap.org; frame-ancestors 'none'")
    rate_limit.STORE.clear()
    keycloak.reset_cache()
