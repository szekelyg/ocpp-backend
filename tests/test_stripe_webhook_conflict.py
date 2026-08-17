"""Foglalt töltőre érkező fizetés: a zárolás nem maradhat az ügyfél kártyáján.

Ha a webhook érkezésekor már fut töltés az adott töltőn, ehhez az intenthez nem
jön létre ChargeSession – így a waiting-timeout háttértask (ami csak sessionöket
néz) sosem oldaná fel a Stripe holdot. A conflict ágnak magának kell elengednie.
"""
import pytest
from sqlalchemy import select

from app.api.routers.payments_stripe import _ensure_session_and_remote_start
from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from app.ocpp.time_utils import utcnow
from tests.conftest import TestSession


@pytest.mark.asyncio
async def test_busy_charge_point_releases_hold():
    async with TestSession() as db:
        cp = ChargePoint(ocpp_id="CP-BUSY", status="charging", last_seen_at=utcnow(),
                         is_published=True)
        db.add(cp)
        await db.flush()

        # Valaki már tölt ezen a töltőn
        running = ChargeSession(
            charge_point_id=cp.id, connector_id=1, ocpp_transaction_id="777",
            started_at=utcnow(), anonymous_email="elso@example.hu",
        )
        db.add(running)

        # Közben egy másik ügyfél kifizeti ugyanezt a töltőt
        intent = ChargingIntent(
            charge_point_id=cp.id, connector_id=1, anonymous_email="masodik@example.hu",
            status="pending_payment", hold_amount_huf=5000, expires_at=utcnow(),
        )
        db.add(intent)
        await db.commit()
        intent_id, running_id = intent.id, running.id

    async with TestSession() as db:
        intent = (await db.execute(
            select(ChargingIntent).where(ChargingIntent.id == intent_id)
        )).scalar_one()
        result = await _ensure_session_and_remote_start(db, intent, "cs_test_123")
        await db.commit()

    assert result["conflict"] is True
    assert result["session_id"] == running_id
    assert result["created"] is False

    async with TestSession() as db:
        intent = (await db.execute(
            select(ChargingIntent).where(ChargingIntent.id == intent_id)
        )).scalar_one()
        assert intent.status == "cancelled", "az intent nem maradhat 'paid'-en session nélkül"
        assert intent.cancel_reason == "charge_point_busy"

        sessions = (await db.execute(select(ChargeSession))).scalars().all()
        assert len(sessions) == 1, "a foglalt töltőre nem jön létre második session"
        assert sessions[0].intent_id is None
