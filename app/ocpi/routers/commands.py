"""OCPI Commands module (CPO = Receiver).

  POST /ocpi/2.2.1/commands/{command}
  command in {START_SESSION, STOP_SESSION, RESERVE_NOW, CANCEL_RESERVATION, UNLOCK_CONNECTOR}

Responds with a CommandResponse immediately; the CommandResult is POSTed to the
partner's response_url from a background task (see services/command_service.py).
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import OcpiCommandResult, OcpiParty

from .. import OCPI_VERSION, enums, status_codes
from ..auth import require_party
from ..envelope import ok
from ..errors import OCPIException
from ..schemas.commands import CommandResponse
from ..services import command_service

router = APIRouter(prefix=f"/{OCPI_VERSION}/commands", tags=["ocpi-commands"])

_KNOWN = {"START_SESSION", "STOP_SESSION", "RESERVE_NOW", "CANCEL_RESERVATION", "UNLOCK_CONNECTOR"}


@router.post("/{command}")
async def post_command(
    command: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    party: OcpiParty = Depends(require_party),
):
    command = command.upper()
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("body must be an object")
    except ValueError as e:
        raise OCPIException(status_codes.INVALID_PARAMETERS, f"Invalid command body: {e}")

    if command not in _KNOWN:
        return ok(CommandResponse(result=enums.CommandResponseType.NOT_SUPPORTED, timeout=0))

    try:
        prepared = await command_service.prepare(db, command, body)
    except (ValidationError, TypeError, ValueError) as e:
        raise OCPIException(status_codes.INVALID_PARAMETERS, f"Invalid command parameters: {e}")

    # Audit row (also used for reservation lookup on CANCEL_RESERVATION).
    record = OcpiCommandResult(
        command=command,
        party_country_code=party.country_code,
        party_party_id=party.party_id,
        response_url=body.get("response_url"),
        request_body=body,
        command_response=prepared.response,
        charge_point_id=prepared.charge_point_id,
        session_id=prepared.session_id,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    if prepared.response == enums.CommandResponseType.ACCEPTED and prepared.exec_info:
        background_tasks.add_task(
            command_service.execute, record.id, prepared.exec_info, party.token_outgoing
        )

    msg = None
    if prepared.message:
        msg = [{"language": "en", "text": prepared.message}]
    return ok(CommandResponse(result=prepared.response, timeout=command_service.COMMAND_TIMEOUT_S, message=msg))
