"""OCPI CDRs module schemas."""
from __future__ import annotations

from typing import Optional

from .common import OCPISchema, OCPIDateTime, GeoLocation, Price
from .sessions import CdrToken, ChargingPeriod
from .tariffs import Tariff


class CdrLocation(OCPISchema):
    id: str
    name: Optional[str] = None
    address: str
    city: str
    postal_code: Optional[str] = None
    country: str
    coordinates: GeoLocation
    evse_uid: str
    evse_id: str
    connector_id: str
    connector_standard: str
    connector_format: str
    connector_power_type: str


class CDR(OCPISchema):
    country_code: str
    party_id: str
    id: str
    start_date_time: OCPIDateTime
    end_date_time: OCPIDateTime
    session_id: Optional[str] = None
    cdr_token: CdrToken
    auth_method: str
    authorization_reference: Optional[str] = None
    cdr_location: CdrLocation
    meter_id: Optional[str] = None
    currency: str
    tariffs: Optional[list[Tariff]] = None
    charging_periods: list[ChargingPeriod]
    total_cost: Price
    total_energy: float          # kWh
    total_time: float            # hours
    invoice_reference_id: Optional[str] = None
    remark: Optional[str] = None
    last_updated: OCPIDateTime
