"""Integrációs API az ek-nak (almérő, elszámolás 2.0 / D lépés) – 2026-09-24.

- Csak Keycloak service-account token az `ek-integracio` realm-szereppel és azp-vel;
  sem sima ügyfél-, sem `ev-admin`-token nem elég (legkisebb jogosultság).
- /charge-points: csak a legördülőhöz kellő mezők, személyes adat nélkül.
- /negyedorak: MeterValues-mintákból pontos negyedórás Wh; minták nélkül a lezárt session
  energiája időarányosan; adat nélküli negyedóra nincs a válaszban (nem 0).

A JWKS-mock és a token-gyár a test_keycloak_auth modulból jön (a keycloak_env autouse).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.models import ChargePoint, ChargeSession, Location, MeterSample
from app.ocpp.time_utils import utcnow
from app.services.negyedorak import (
    MODSZER_ARANY,
    MODSZER_MINTA,
    SessionAdat,
    negyedoras_energia,
)
from tests.conftest import TestSession
from tests.test_keycloak_auth import bearer, keycloak_env, make_token  # noqa: F401

LIST_URL = "/api/integration/charge-points"

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)   # negyedóra-határ
U0 = int(T0.timestamp())
assert U0 % 900 == 0


def sa_token(role="ek-integracio", azp="ek-integracio", aud=("ev", "account"), **kw):
    """Service-account access token: nincs e-mail, van realm-szerep, azp = a kliens."""
    roles = ["default-roles-ugyfelek"] + ([role] if role else [])
    return make_token(
        azp=azp, aud=list(aud) if aud else None, sub="sa-ek-integracio",
        extra={"realm_access": {"roles": roles}, "preferred_username": "service-account-ek-integracio"},
        drop=("email", "email_verified", "name"), **kw,
    )


def m(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


async def _seed_cp(ocpp_id="nograd_var_1", **kw):
    async with TestSession() as s:
        loc = Location(name="Nógrádi vár", address_text="2642 Nógrád, Vár")
        s.add(loc)
        await s.flush()
        cp = ChargePoint(ocpp_id=ocpp_id, status="available", location_id=loc.id,
                         max_power_kw=22.0, is_published=True, **kw)
        s.add(cp)
        await s.commit()
        return cp.id


async def _seed_session(cp_id, start, stop=None, *, meter_start=None, energy_kwh=None,
                        samples=(), tx=None, email="titkos@example.hu"):
    async with TestSession() as s:
        cs = ChargeSession(charge_point_id=cp_id, connector_id=1, started_at=start, finished_at=stop,
                           meter_start_wh=meter_start, energy_kwh=energy_kwh,
                           ocpp_transaction_id=tx, anonymous_email=email)
        s.add(cs)
        await s.flush()
        for ts, wh in samples:
            s.add(MeterSample(charge_point_id=cp_id, session_id=cs.id, connector_id=1, ts=ts,
                              energy_wh_total=wh, power_w=0.0))
        await s.commit()
        return cs.id


def nq_url(cp="nograd_var_1", frm=U0, to=U0 + 4 * 3600):
    return f"/api/integration/charge-points/{cp}/negyedorak?from={frm}&to={to}"


# ── hozzáférés ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_account_ok(client):
    r = await client.get(LIST_URL, headers=bearer(sa_token()))
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_missing_header_401(client):
    r = await client.get(LIST_URL)
    assert r.status_code == 401
    assert r.json()["detail"] == "missing_bearer_token"
    r = await client.get(LIST_URL, headers={"Authorization": "Basic YWRtaW46dGVzdC1hZG1pbi1wdw=="})
    assert r.status_code == 401      # nincs Basic vész-út


@pytest.mark.asyncio
async def test_user_and_admin_tokens_are_not_enough(client):
    # sima ügyfél (ev SPA token)
    r = await client.get(LIST_URL, headers=bearer(make_token(email="ugyfel@example.hu")))
    assert r.status_code == 403
    assert r.json()["detail"] == "integration_role_missing"
    # ev-admin: más szerep – ez sem ad integrációs jogot
    tok = make_token(email="admin@example.hu", extra={"realm_access": {"roles": ["ev-admin"]}})
    r = await client.get(LIST_URL, headers=bearer(tok))
    assert r.status_code == 403
    # és fordítva: az integrációs token nem admin
    r = await client.get("/api/admin/stats", headers=bearer(sa_token()))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_role_but_wrong_client_403(client):
    # egy felhasználó, akire véletlenül rákerült a szerep, az ev SPA-ból NEM éri el
    r = await client.get(LIST_URL, headers=bearer(sa_token(azp="ev")))
    assert r.status_code == 403
    assert r.json()["detail"] == "integration_client_not_allowed"


@pytest.mark.asyncio
async def test_audience_required(client):
    # audience-mapper nélkül (aud csak `account`) a token nem ev-nek szól → 401
    r = await client.get(LIST_URL, headers=bearer(sa_token(aud=("account",))))
    assert r.status_code == 401
    assert r.json()["detail"] == "keycloak_invalid_audience"


@pytest.mark.asyncio
async def test_expired_401(client):
    r = await client.get(LIST_URL, headers=bearer(sa_token(exp_in=-120)))
    assert r.status_code == 401
    assert r.json()["detail"] == "keycloak_token_expired"


@pytest.mark.asyncio
async def test_role_and_clients_from_env(client, monkeypatch):
    monkeypatch.setenv("KEYCLOAK_INTEGRATION_ROLE", "almero-olvaso")
    assert (await client.get(LIST_URL, headers=bearer(sa_token()))).status_code == 403
    assert (await client.get(LIST_URL, headers=bearer(sa_token(role="almero-olvaso")))).status_code == 200
    monkeypatch.setenv("KEYCLOAK_INTEGRATION_CLIENTS", "ek-integracio, ek-teszt")
    tok = sa_token(role="almero-olvaso", azp="ek-teszt")
    assert (await client.get(LIST_URL, headers=bearer(tok))).status_code == 200
    # üres lista = csak a szerep számít (a tokennek az aud/azp-ellenőrzésen így is át kell mennie)
    monkeypatch.setenv("KEYCLOAK_INTEGRATION_CLIENTS", "")
    tok = sa_token(role="almero-olvaso", azp="portal", aud=None)
    assert (await client.get(LIST_URL, headers=bearer(tok))).status_code == 200


@pytest.mark.asyncio
async def test_keycloak_disabled_503(client, monkeypatch):
    monkeypatch.delenv("KEYCLOAK_ISSUER")
    r = await client.get(LIST_URL, headers=bearer(sa_token()))
    assert r.status_code == 503
    assert r.json()["detail"] == "integration_not_configured"


# ── töltőlista ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_charge_point_list_fields(client):
    await _seed_cp("nograd_var_1", last_seen_at=utcnow())
    async with TestSession() as s:
        s.add(ChargePoint(ocpp_id="Nograd-Var-2-uj", status="available", is_published=False))
        await s.commit()
    r = await client.get(LIST_URL, headers=bearer(sa_token()))
    assert r.status_code == 200
    data = r.json()
    assert [d["id"] for d in data] == ["Nograd-Var-2-uj", "nograd_var_1"]
    uj, var1 = data
    assert var1 == {
        "id": "nograd_var_1", "nev": "Nógrádi vár (nograd_var_1)", "helyszin": "Nógrádi vár",
        "cim": "2642 Nógrád, Vár", "max_power_kw": 22.0, "online": True, "allapot": "available",
        "publikalt": True,
    }
    assert uj["nev"] == "Nograd-Var-2-uj" and uj["online"] is False and uj["publikalt"] is False
    assert "titkos" not in r.text and "@" not in r.text


# ── negyedórák ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_negyedorak_from_meter_values(client):
    cp = await _seed_cp()
    # élettartam-regiszter, meterStart = 100 000 Wh; 10:00–10:15: 3000 Wh, 10:15–10:30: 1500 Wh,
    # 10:30–10:45: 0 Wh (az autó tele, a session még nyitva volt)
    samples = [(m(5), 101_000), (m(10), 102_000), (m(15), 103_000),
               (m(20), 103_500), (m(25), 104_000), (m(30), 104_500),
               (m(40), 104_500)]
    await _seed_session(cp, m(0), m(45), meter_start=100_000, energy_kwh=4.5, samples=samples, tx="1")
    r = await client.get(nq_url(), headers=bearer(sa_token()))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "nograd_var_1" and body["egyseg"] == "Wh" and body["negyedora_s"] == 900
    assert body["negyedorak"] == [
        {"ts": U0, "wh": 3000.0, "modszer": MODSZER_MINTA},
        {"ts": U0 + 900, "wh": 1500.0, "modszer": MODSZER_MINTA},
        {"ts": U0 + 1800, "wh": 0.0, "modszer": MODSZER_MINTA},   # mért nulla: van sor
    ]
    # a session előtti/utáni negyedórák: nincs sor


@pytest.mark.asyncio
async def test_negyedorak_session_proportional_without_samples(client):
    cp = await _seed_cp()
    await _seed_session(cp, m(5), m(35), meter_start=0, energy_kwh=3.0)
    r = await client.get(nq_url(), headers=bearer(sa_token()))
    assert r.status_code == 200
    assert r.json()["negyedorak"] == [
        {"ts": U0, "wh": 1000.0, "modszer": MODSZER_ARANY},
        {"ts": U0 + 900, "wh": 1500.0, "modszer": MODSZER_ARANY},
        {"ts": U0 + 1800, "wh": 500.0, "modszer": MODSZER_ARANY},
    ]


@pytest.mark.asyncio
async def test_negyedorak_no_data_no_rows(client):
    cp = await _seed_cp()
    # energia nélküli (félbemaradt) session → nincs miből számolni
    await _seed_session(cp, m(0), m(30), meter_start=None, energy_kwh=None)
    r = await client.get(nq_url(), headers=bearer(sa_token()))
    assert r.status_code == 200
    assert r.json()["negyedorak"] == []


@pytest.mark.asyncio
async def test_negyedorak_window_alignment_and_clipping(client):
    cp = await _seed_cp()
    await _seed_session(cp, m(0), m(60), meter_start=0, energy_kwh=4.0)
    # nem igazított ablak: from lefelé, to felfelé 900-ra
    r = await client.get(nq_url(frm=U0 + 1000, to=U0 + 2000), headers=bearer(sa_token()))
    body = r.json()
    assert body["from"] == U0 + 900 and body["to"] == U0 + 2700
    assert [q["ts"] for q in body["negyedorak"]] == [U0 + 900, U0 + 1800]
    assert all(q["wh"] == 1000.0 for q in body["negyedorak"])


@pytest.mark.asyncio
async def test_negyedorak_only_closed_quarters(client):
    await _seed_cp()
    most = int(utcnow().timestamp())
    r = await client.get(nq_url(frm=most - 3600, to=most + 3600), headers=bearer(sa_token()))
    assert r.status_code == 200
    assert r.json()["to"] == most // 900 * 900


@pytest.mark.asyncio
async def test_negyedorak_validation(client):
    await _seed_cp()
    h = bearer(sa_token())
    r = await client.get(nq_url(frm=U0, to=U0 + 31 * 86400 + 900), headers=h)
    assert r.status_code == 400 and r.json()["detail"] == "window_too_large"
    assert (await client.get(nq_url(frm=U0, to=U0 + 31 * 86400), headers=h)).status_code == 200
    r = await client.get(nq_url(frm=U0, to=U0), headers=h)
    assert r.status_code == 400 and r.json()["detail"] == "invalid_window"
    r = await client.get(nq_url(cp="nincs-ilyen"), headers=h)
    assert r.status_code == 404
    r = await client.get("/api/integration/charge-points/nograd_var_1/negyedorak?from=1", headers=h)
    assert r.status_code == 422
    # jogosultság itt is kell
    assert (await client.get(nq_url())).status_code == 401


@pytest.mark.asyncio
async def test_negyedorak_two_connectors_sum(client):
    cp = await _seed_cp()
    await _seed_session(cp, m(0), m(15), meter_start=0, energy_kwh=1.0, tx="a")
    await _seed_session(cp, m(0), m(15), meter_start=0, energy_kwh=2.0, tx="b")
    r = await client.get(nq_url(), headers=bearer(sa_token()))
    assert r.json()["negyedorak"] == [{"ts": U0, "wh": 3000.0, "modszer": MODSZER_ARANY}]


# ── a számítás (tiszta függvény) ─────────────────────────────────────────────

def _q(sessions, tol=U0, ig=U0 + 7200):
    return negyedoras_energia(sessions, tol=tol, ig=ig, most=U0 + 10 * 3600)


def test_session_relative_register():
    # meterStart élettartam-skálán (50 000), a MeterValues viszont session-relatív (0-ról indul)
    s = SessionAdat(started_at=m(0), finished_at=m(30), meter_start_wh=50_000, energy_kwh=2.0,
                    mintak=[(m(1), 0.0), (m(15), 1500.0), (m(29), 2000.0)])
    out = _q([s])
    assert round(out[U0][0], 1) == 1500.0
    assert round(out[U0 + 900][0], 1) == 500.0
    assert out[U0][1] == MODSZER_MINTA


def test_scaled_down_to_billed_energy():
    # a minták 4000 Wh-t mutatnak, de a számlázott (energy_kwh) csak 2 kWh → arányos leskálázás
    s = SessionAdat(started_at=m(0), finished_at=m(30), meter_start_wh=0, energy_kwh=2.0,
                    mintak=[(m(15), 3000.0), (m(30), 4000.0)])
    out = _q([s])
    assert round(out[U0][0] + out[U0 + 900][0], 1) == 2000.0
    assert round(out[U0][0], 1) == 1500.0


def test_open_session_ends_at_last_sample():
    s = SessionAdat(started_at=m(0), finished_at=None, meter_start_wh=1000, energy_kwh=None,
                    mintak=[(m(10), 1500.0), (m(20), 2500.0)])
    out = _q([s])
    assert round(out[U0][0], 1) == 1000.0          # 0→10 perc: 500, 10→15: 500
    assert round(out[U0 + 900][0], 1) == 500.0     # 15→20 perc: 500; utána még nincs mérés
    assert U0 + 1800 not in out


def test_register_never_decreases():
    s = SessionAdat(started_at=m(0), finished_at=m(15), meter_start_wh=0, energy_kwh=1.0,
                    mintak=[(m(5), 600.0), (m(7), 100.0), (m(10), 900.0)])
    out = _q([s])
    assert round(out[U0][0], 1) == 1000.0


def test_samples_outside_session_ignored():
    s = SessionAdat(started_at=m(15), finished_at=m(30), meter_start_wh=0, energy_kwh=1.0,
                    mintak=[(m(0), 9999.0), (m(20), 500.0), (m(45), 99_999.0)])
    out = _q([s])
    assert list(out) == [U0 + 900]
    assert round(out[U0 + 900][0], 1) == 1000.0
