"""StartTransaction párosítása a kifizetett sessionhöz.

A fizetéskor a session connector_id-ja abból jön, amit a frontend küld (1), a
StartTransaction viszont azt küldi vissza, amit a töltő gondol (0, 1, 2 vagy
semmi). Ha ezen elcsúszik a párosítás, a kifizetett session tx nélkül marad
(15 perc múlva timeout + zárolás feloldás), a tényleges töltés pedig egy
fizetéshez nem kötött, számlázatlan sessionbe fut.
"""
import pytest
from sqlalchemy import select

from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from app.ocpp.handlers.transactions import start_transaction
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession

import app.ocpp.handlers.transactions as _tx_mod
_tx_mod.AsyncSessionLocal = TestSession


async def _cp(ocpp_id):
    async with TestSession() as s:
        cp = ChargePoint(ocpp_id=ocpp_id, status="available", last_seen_at=utcnow(),
                         is_published=True)
        s.add(cp)
        await s.commit()
        return cp.id


async def _paid_session(cp_id, connector_id=1):
    """Amit a Stripe webhook hoz létre: intent + session, tx nélkül."""
    async with TestSession() as s:
        intent = ChargingIntent(
            charge_point_id=cp_id, connector_id=connector_id,
            anonymous_email="ugyfel@example.hu", status="paid",
            hold_amount_huf=5000, expires_at=utcnow(),
        )
        s.add(intent)
        await s.flush()
        cs = ChargeSession(
            charge_point_id=cp_id, connector_id=connector_id, ocpp_transaction_id=None,
            started_at=utcnow(), anonymous_email="ugyfel@example.hu", intent_id=intent.id,
        )
        s.add(cs)
        await s.commit()
        return cs.id


async def _sessions():
    async with TestSession() as s:
        return (await s.execute(select(ChargeSession).order_by(ChargeSession.id))).scalars().all()


@pytest.mark.parametrize("payload_connector", [2, 0, None])
@pytest.mark.asyncio
async def test_paid_session_adopted_on_connector_mismatch(payload_connector):
    cp_id = await _cp(f"CP-MM-{payload_connector}")
    paid_id = await _paid_session(cp_id, connector_id=1)

    payload = {"idTag": "ANON", "timestamp": "2026-08-10T10:00:00Z", "meterStart": 0}
    if payload_connector is not None:
        payload["connectorId"] = payload_connector

    tx_id = await start_transaction(f"CP-MM-{payload_connector}", payload)

    rows = await _sessions()
    assert len(rows) == 1, "nem jöhet létre külön, fizetéshez nem kötött session"
    cs = rows[0]
    assert cs.id == paid_id
    assert tx_id == paid_id
    assert cs.ocpp_transaction_id == str(paid_id), "a kifizetett session megkapta a tranzakciót"
    assert cs.intent_id is not None
    assert cs.anonymous_email == "ugyfel@example.hu", "van hova bizonylatot küldeni"
    if payload_connector is not None:
        assert cs.connector_id == payload_connector, "a töltő valós csatlakozója rögzül"


@pytest.mark.asyncio
async def test_exact_connector_match_still_reuses():
    cp_id = await _cp("CP-EXACT")
    paid_id = await _paid_session(cp_id, connector_id=1)

    await start_transaction("CP-EXACT", {
        "connectorId": 1, "idTag": "ANON",
        "timestamp": "2026-08-10T10:00:00Z", "meterStart": 1500,
    })

    rows = await _sessions()
    assert len(rows) == 1
    assert rows[0].id == paid_id
    assert rows[0].meter_start_wh == 1500


@pytest.mark.asyncio
async def test_walk_up_charge_creates_new_session():
    """Nincs kifizetett, indulásra váró session (pl. RFID-s indítás) → új session."""
    await _cp("CP-WALKUP")

    await start_transaction("CP-WALKUP", {
        "connectorId": 1, "idTag": "RFID123",
        "timestamp": "2026-08-10T10:00:00Z", "meterStart": 0,
    })

    rows = await _sessions()
    assert len(rows) == 1
    assert rows[0].intent_id is None
    assert rows[0].user_tag == "RFID123"
    assert rows[0].ocpp_transaction_id == str(rows[0].id)


@pytest.mark.asyncio
async def test_running_session_is_not_hijacked():
    """Egy már futó (tx-es) sessiont egy új StartTransaction nem vehet át."""
    cp_id = await _cp("CP-RUNNING")
    first_id = await _paid_session(cp_id, connector_id=1)
    await start_transaction("CP-RUNNING", {
        "connectorId": 1, "idTag": "ANON",
        "timestamp": "2026-08-10T10:00:00Z", "meterStart": 0,
    })

    # ugyanaz a töltő újra indít, közben az első session nyitva van
    await start_transaction("CP-RUNNING", {
        "connectorId": 1, "idTag": "MASIK",
        "timestamp": "2026-08-10T11:00:00Z", "meterStart": 500,
    })

    rows = await _sessions()
    assert len(rows) == 2, "a futó session mellé új sor kell"
    first = [r for r in rows if r.id == first_id][0]
    assert first.user_tag == "ANON"
    assert first.ocpp_transaction_id == str(first_id)
