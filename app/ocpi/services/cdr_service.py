"""Snapshot a finished ChargeSession into an immutable OCPI CDR row.

CDRs must not change after the fact, but our cost derives from mutable env
pricing — so we freeze a snapshot at session completion. ``snapshot_session_cdr``
is the best-effort hook called from the OCPP completion paths; it opens its own
DB session and never raises into the caller.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import ChargePoint, ChargeSession, OcpiCdr
from app.ocpp.time_utils import utcnow

from ..mappers.cdrs import build_cdr_from_session

logger = logging.getLogger("ocpi")


async def snapshot_cdr(db: AsyncSession, cs: ChargeSession) -> Optional[OcpiCdr]:
    """Idempotently create the CDR snapshot for a finished session.

    ``cs`` must have ``charge_point`` (and its ``location``) eager-loaded.
    Returns the existing row if already snapshotted, None if the session isn't
    eligible (not finished).
    """
    if cs.finished_at is None:
        return None

    cdr_id = str(cs.id)
    existing = (
        await db.execute(select(OcpiCdr).where(OcpiCdr.cdr_id == cdr_id))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    cdr = build_cdr_from_session(cs)
    row = OcpiCdr(
        cdr_id=cdr.id,
        session_id=cs.id,
        country_code=cdr.country_code,
        party_id=cdr.party_id,
        start_date_time=cs.started_at,
        end_date_time=cs.finished_at,
        cdr_token=cdr.cdr_token.model_dump(mode="json", exclude_none=True),
        auth_method=cdr.auth_method,
        cdr_location=cdr.cdr_location.model_dump(mode="json", exclude_none=True),
        currency=cdr.currency,
        tariffs=[t.model_dump(mode="json", exclude_none=True) for t in (cdr.tariffs or [])],
        charging_periods=[p.model_dump(mode="json", exclude_none=True) for p in cdr.charging_periods],
        total_energy=cdr.total_energy,
        total_time=cdr.total_time,
        total_cost=cdr.total_cost.model_dump(mode="json", exclude_none=True),
        invoice_reference_id=cdr.invoice_reference_id,
        last_updated=utcnow(),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def snapshot_session_cdr(session_id: int) -> None:
    """Best-effort hook: snapshot the CDR for a just-finished session by id.

    Opens its own DB session and swallows all errors so it can be called from the
    OCPP completion paths without affecting the charging/billing flow.
    """
    try:
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            cs = (
                await db.execute(
                    select(ChargeSession)
                    .options(selectinload(ChargeSession.charge_point).selectinload(ChargePoint.location))
                    .where(ChargeSession.id == session_id)
                )
            ).scalar_one_or_none()
            if cs is None:
                return
            already = (
                await db.execute(select(OcpiCdr.id).where(OcpiCdr.cdr_id == str(cs.id)))
            ).scalar_one_or_none() is not None
            row = await snapshot_cdr(db, cs)
        # Push the freshly-created CDR to registered roaming partners (best-effort).
        if row is not None and not already:
            from .push_service import schedule_push_cdr
            schedule_push_cdr(row.cdr_id)
    except Exception:
        logger.exception(f"OCPI CDR snapshot failed for session_id={session_id}")
