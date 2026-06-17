"""OCPI Sessions module schemas (also defines CdrToken/ChargingPeriod reused by CDRs)."""
from __future__ import annotations

from typing import Optional

from .common import OCPISchema, OCPIDateTime, Price


class CdrToken(OCPISchema):
    country_code: str
    party_id: str
    uid: str
    type: str               # TokenType
    contract_id: str


class CdrDimension(OCPISchema):
    type: str               # CdrDimensionType: ENERGY / TIME / ...
    volume: float


class ChargingPeriod(OCPISchema):
    start_date_time: OCPIDateTime
    dimensions: list[CdrDimension]
    tariff_id: Optional[str] = None


class Session(OCPISchema):
    country_code: str
    party_id: str
    id: str
    start_date_time: OCPIDateTime
    end_date_time: Optional[OCPIDateTime] = None
    kwh: float
    cdr_token: CdrToken
    auth_method: str        # AuthMethod
    authorization_reference: Optional[str] = None
    location_id: str
    evse_uid: str
    connector_id: str
    meter_id: Optional[str] = None
    currency: str
    charging_periods: Optional[list[ChargingPeriod]] = None
    total_cost: Optional[Price] = None
    status: str             # SessionStatus
    last_updated: OCPIDateTime
