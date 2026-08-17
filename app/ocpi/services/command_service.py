"""OCPI Commands orchestration (CPO = Receiver).

Async pattern: validate + resolve the target, respond ACCEPTED immediately, then
(as a background task) run the OCPP command through app/ocpp/registry.py and POST
a CommandResult to the partner's ``response_url``.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import ChargePoint, ChargeSession, OcpiCommandResult
from app.ocpp import registry
from app.ocpp.time_utils import utcnow

from .. import enums, ids, push
from ..schemas.commands import (
    CancelReservation,
    CommandResponse,
    ReserveNow,
    StartSession,
    StopSession,
    UnlockConnector,
)

logger = logging.getLogger("ocpi")

COMMAND_TIMEOUT_S = 30

# OCPP CALL result status -> OCPI CommandResultType.
_OCPP_TO_RESULT = {
    "accepted": enums.CommandResultType.ACCEPTED,
    "rejected": enums.CommandResultType.REJECTED,
    "occupied": enums.CommandResultType.EVSE_OCCUPIED,
    "faulted": enums.CommandResultType.FAILED,
    "unavailable": enums.CommandResultType.EVSE_INOPERATIVE,
}


@dataclass
class Prepared:
    response: str                       # CommandResponseType
    exec_info: Optional[dict] = None    # what the background task should run
    charge_point_id: Optional[int] = None
    session_id: Optional[int] = None
    message: Optional[str] = None


async def _find_cp(db: AsyncSession, location_id: str, evse_uid: Optional[str]) -> Optional[ChargePoint]:
    pk = ids.parse_location_id(location_id)
    if pk is None:
        return None
    # Publikálatlan (konfigurálásra váró) töltőre roaming parancs sem futhat.
    q = select(ChargePoint).where(
        ChargePoint.location_id == pk, ChargePoint.is_published.is_(True)
    )
    rows = (await db.execute(q)).scalars().all()
    if not rows:
        return None
    if evse_uid:
        for cp in rows:
            if ids.evse_uid(cp) == evse_uid:
                return cp
        return None
    # evse_uid omitted: only unambiguous when the location has a single EVSE
    return rows[0] if len(rows) == 1 else None


async def _find_session(db: AsyncSession, session_id: str) -> Optional[ChargeSession]:
    conds = [ChargeSession.ocpi_session_id == session_id]
    if session_id.isdigit():
        conds.append(ChargeSession.id == int(session_id))
    return (
        await db.execute(
            select(ChargeSession).options(selectinload(ChargeSession.charge_point)).where(or_(*conds))
        )
    ).scalar_one_or_none()


def _connector_int(connector_id: Optional[str]) -> int:
    if connector_id and str(connector_id).isdigit():
        return int(connector_id)
    return 1


async def prepare(db: AsyncSession, command: str, body: dict) -> Prepared:
    """Validate + resolve a command; decide the immediate CommandResponse."""
    if command == "START_SESSION":
        data = StartSession(**body)
        cp = await _find_cp(db, data.location_id, data.evse_uid)
        if cp is None:
            return Prepared(enums.CommandResponseType.REJECTED, message="Unknown location/EVSE")
        return Prepared(
            enums.CommandResponseType.ACCEPTED,
            exec_info={
                "action": "RemoteStartTransaction",
                "cp_ocpp_id": cp.ocpp_id,
                "connector_id": _connector_int(data.connector_id),
                "id_tag": data.token.uid,
                "response_url": data.response_url,
            },
            charge_point_id=cp.id,
        )

    if command == "STOP_SESSION":
        data = StopSession(**body)
        cs = await _find_session(db, data.session_id)
        if cs is None or cs.finished_at is not None:
            return Prepared(enums.CommandResponseType.UNKNOWN_SESSION, message="Unknown or finished session")
        if not cs.ocpp_transaction_id or cs.charge_point is None:
            return Prepared(enums.CommandResponseType.REJECTED, message="Session not active on charger")
        return Prepared(
            enums.CommandResponseType.ACCEPTED,
            exec_info={
                "action": "RemoteStopTransaction",
                "cp_ocpp_id": cs.charge_point.ocpp_id,
                "transaction_id": cs.ocpp_transaction_id,
                "response_url": data.response_url,
            },
            charge_point_id=cs.charge_point_id,
            session_id=cs.id,
        )

    if command == "UNLOCK_CONNECTOR":
        data = UnlockConnector(**body)
        cp = await _find_cp(db, data.location_id, data.evse_uid)
        if cp is None:
            return Prepared(enums.CommandResponseType.REJECTED, message="Unknown location/EVSE")
        return Prepared(
            enums.CommandResponseType.ACCEPTED,
            exec_info={
                "action": "UnlockConnector",
                "cp_ocpp_id": cp.ocpp_id,
                "payload": {"connectorId": _connector_int(data.connector_id)},
                "response_url": data.response_url,
            },
            charge_point_id=cp.id,
        )

    if command == "RESERVE_NOW":
        data = ReserveNow(**body)
        cp = await _find_cp(db, data.location_id, data.evse_uid)
        if cp is None:
            return Prepared(enums.CommandResponseType.REJECTED, message="Unknown location/EVSE")
        return Prepared(
            enums.CommandResponseType.ACCEPTED,
            exec_info={
                "action": "ReserveNow",
                "cp_ocpp_id": cp.ocpp_id,
                "payload": {
                    "connectorId": 1,
                    "expiryDate": data.expiry_date,
                    "idTag": data.token.uid,
                    "reservationId": int(data.reservation_id) if data.reservation_id.isdigit() else data.reservation_id,
                },
                "response_url": data.response_url,
            },
            charge_point_id=cp.id,
        )

    if command == "CANCEL_RESERVATION":
        data = CancelReservation(**body)
        cp = await _find_reservation_cp(db, data.reservation_id)
        if cp is None:
            return Prepared(enums.CommandResponseType.REJECTED, message="Unknown reservation")
        rid = int(data.reservation_id) if data.reservation_id.isdigit() else data.reservation_id
        return Prepared(
            enums.CommandResponseType.ACCEPTED,
            exec_info={
                "action": "CancelReservation",
                "cp_ocpp_id": cp.ocpp_id,
                "payload": {"reservationId": rid},
                "response_url": data.response_url,
            },
            charge_point_id=cp.id,
        )

    return Prepared(enums.CommandResponseType.NOT_SUPPORTED, message=f"Unknown command {command}")


async def _find_reservation_cp(db: AsyncSession, reservation_id: str) -> Optional[ChargePoint]:
    """Find the charge point of a prior RESERVE_NOW with this reservation_id."""
    rows = (
        await db.execute(
            select(OcpiCommandResult)
            .where(OcpiCommandResult.command == "RESERVE_NOW")
            .order_by(OcpiCommandResult.id.desc())
            .limit(200)
        )
    ).scalars().all()
    for row in rows:
        body = row.request_body or {}
        if str(body.get("reservation_id")) == str(reservation_id) and row.charge_point_id:
            return (await db.execute(select(ChargePoint).where(ChargePoint.id == row.charge_point_id))).scalar_one_or_none()
    return None


def _map_ocpp_status(status: Optional[str]) -> str:
    return _OCPP_TO_RESULT.get((status or "").strip().lower(), enums.CommandResultType.REJECTED)


async def execute(record_id: Optional[int], exec_info: dict, outgoing_token: Optional[str]) -> None:
    """Background task: run the OCPP command and POST the CommandResult."""
    action = exec_info["action"]
    cp_ocpp_id = exec_info["cp_ocpp_id"]
    response_url = exec_info.get("response_url")
    result_type = enums.CommandResultType.FAILED

    try:
        if action == "RemoteStartTransaction":
            ocpp = await registry.remote_start_transaction(cp_ocpp_id, exec_info["connector_id"], exec_info["id_tag"])
        elif action == "RemoteStopTransaction":
            ocpp = await registry.remote_stop_transaction(cp_ocpp_id, exec_info["transaction_id"])
        else:
            ocpp = await registry.send_call_and_wait(cp_ocpp_id, action, exec_info["payload"])
        result_type = _map_ocpp_status(ocpp.get("status") if isinstance(ocpp, dict) else None)
    except (RuntimeError, asyncio.TimeoutError) as e:
        logger.warning(f"OCPI command {action} cp={cp_ocpp_id} could not reach charger: {e}")
        result_type = enums.CommandResultType.TIMEOUT
    except Exception:
        logger.exception(f"OCPI command {action} cp={cp_ocpp_id} failed")
        result_type = enums.CommandResultType.FAILED

    status_code = 0
    if response_url:
        status_code = await push.raw_post(response_url, outgoing_token, {"result": result_type})

    if record_id is not None:
        await _finalize_record(record_id, result_type, status_code)


async def _finalize_record(record_id: int, result_type: str, status_code: int) -> None:
    try:
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            row = (await db.execute(select(OcpiCommandResult).where(OcpiCommandResult.id == record_id))).scalar_one_or_none()
            if row is not None:
                row.command_result = result_type
                row.callback_status_code = status_code
                row.completed_at = utcnow()
                await db.commit()
    except Exception:
        logger.exception(f"OCPI command result finalize failed record_id={record_id}")
