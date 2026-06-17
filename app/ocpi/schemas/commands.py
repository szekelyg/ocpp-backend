"""OCPI Commands module schemas (CPO = Receiver)."""
from __future__ import annotations

from typing import Optional

from .common import OCPISchema, DisplayText
from .tokens import Token


class CommandResponse(OCPISchema):
    result: str                     # CommandResponseType: ACCEPTED / REJECTED / NOT_SUPPORTED / UNKNOWN_SESSION
    timeout: int                    # seconds the partner should wait for the CommandResult
    message: Optional[list[DisplayText]] = None


class CommandResult(OCPISchema):
    result: str                     # CommandResultType
    message: Optional[list[DisplayText]] = None


# --- Command request bodies (lenient parsing) ----------------------------

class StartSession(OCPISchema):
    response_url: str
    token: Token
    location_id: str
    evse_uid: Optional[str] = None
    connector_id: Optional[str] = None
    authorization_reference: Optional[str] = None


class StopSession(OCPISchema):
    response_url: str
    session_id: str


class ReserveNow(OCPISchema):
    response_url: str
    token: Token
    expiry_date: str
    reservation_id: str
    location_id: str
    evse_uid: Optional[str] = None
    authorization_reference: Optional[str] = None


class CancelReservation(OCPISchema):
    response_url: str
    reservation_id: str


class UnlockConnector(OCPISchema):
    response_url: str
    location_id: str
    evse_uid: str
    connector_id: str
