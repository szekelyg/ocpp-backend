"""Outbound OCPI push (CPO = Sender).

When our Locations/Sessions/CDRs change we PUT/POST them to every registered
partner's Receiver endpoint. All pushes are best-effort and fire-and-forget: a
missing endpoint (no partner configured the module) or a transport error is
logged and ignored, never affecting the OCPP/charging flow.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import ChargePoint, ChargeSession, Location, OcpiCdr, OcpiParty

from .. import config, enums, push
from ..mappers.cdrs import cdr_orm_to_schema
from ..mappers.locations import location_from_orm
from ..mappers.sessions import session_from_orm

logger = logging.getLogger("ocpi")


def _receiver_url(party: OcpiParty, module_id: str) -> Optional[str]:
    for ep in (party.endpoints or []):
        if ep.get("identifier") == module_id and ep.get("role") == enums.InterfaceRole.RECEIVER:
            return ep.get("url")
    return None


async def _registered_parties(db) -> list[OcpiParty]:
    return list((await db.execute(select(OcpiParty).where(OcpiParty.status == "REGISTERED"))).scalars().all())


def _object_url(base: str, object_id: str) -> str:
    return f"{base.rstrip('/')}/{config.country_code()}/{config.party_id()}/{object_id}"


# --- public push entrypoints ---------------------------------------------

async def push_location(location_id: int) -> None:
    from app.db.session import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            loc = (
                await db.execute(
                    select(Location)
                    .options(selectinload(Location.charge_points).selectinload(ChargePoint.location))
                    .where(Location.id == location_id)
                )
            ).scalar_one_or_none()
            if loc is None:
                return
            parties = await _registered_parties(db)
            payload = location_from_orm(loc).model_dump(mode="json", exclude_none=True)
            obj_id = str(loc.id)
        for p in parties:
            base = _receiver_url(p, enums.ModuleID.LOCATIONS)
            if not base:
                continue
            try:
                await push.put_json(_object_url(base, obj_id), p.token_outgoing, payload)
            except push.OCPIClientError as e:
                logger.warning(f"push_location to {p.party_id} failed: {e}")
    except Exception:
        logger.exception(f"push_location error location_id={location_id}")


async def push_session(session_id: int) -> None:
    from app.db.session import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            cs = (
                await db.execute(
                    select(ChargeSession).options(selectinload(ChargeSession.charge_point)).where(ChargeSession.id == session_id)
                )
            ).scalar_one_or_none()
            if cs is None:
                return
            parties = await _registered_parties(db)
            payload = session_from_orm(cs).model_dump(mode="json", exclude_none=True)
            obj_id = cs.ocpi_session_id or str(cs.id)
        for p in parties:
            base = _receiver_url(p, enums.ModuleID.SESSIONS)
            if not base:
                continue
            try:
                await push.put_json(_object_url(base, obj_id), p.token_outgoing, payload)
            except push.OCPIClientError as e:
                logger.warning(f"push_session to {p.party_id} failed: {e}")
    except Exception:
        logger.exception(f"push_session error session_id={session_id}")


async def push_cdr(cdr_id: str) -> None:
    from app.db.session import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(OcpiCdr).where(OcpiCdr.cdr_id == cdr_id))).scalar_one_or_none()
            if row is None:
                return
            parties = await _registered_parties(db)
            payload = cdr_orm_to_schema(row).model_dump(mode="json", exclude_none=True)
        for p in parties:
            base = _receiver_url(p, enums.ModuleID.CDRS)
            if not base:
                continue
            # CDRs Receiver is a POST (creates a new immutable CDR on their side).
            await push.raw_post(base, p.token_outgoing, payload)
    except Exception:
        logger.exception(f"push_cdr error cdr_id={cdr_id}")


# --- fire-and-forget scheduling ------------------------------------------

def _log_task_exc(task: "asyncio.Task") -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.warning(f"OCPI push task failed: {exc!r}")


def schedule(coro) -> None:
    """Schedule a push coroutine on the running loop; no-op if there's no loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("schedule(): no running loop, push skipped")
        return
    task = loop.create_task(coro)
    task.add_done_callback(_log_task_exc)


def schedule_push_location(location_id: Optional[int]) -> None:
    if location_id is not None:
        schedule(push_location(location_id))


def schedule_push_session(session_id: int) -> None:
    schedule(push_session(session_id))


def schedule_push_cdr(cdr_id: str) -> None:
    schedule(push_cdr(cdr_id))
