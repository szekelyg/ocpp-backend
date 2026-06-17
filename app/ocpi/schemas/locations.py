"""OCPI Locations module schemas (Location -> EVSE -> Connector)."""
from __future__ import annotations

from typing import Optional

from .common import OCPISchema, OCPIDateTime, GeoLocation, BusinessDetails, DisplayText


class Connector(OCPISchema):
    id: str                                 # "1" (flat model: one connector per EVSE)
    standard: str                           # ConnectorType
    format: str                             # SOCKET / CABLE
    power_type: str                         # AC_1_PHASE / AC_3_PHASE / DC
    max_voltage: int
    max_amperage: int
    max_electric_power: Optional[int] = None  # watts
    tariff_ids: list[str] = []
    last_updated: OCPIDateTime


class EVSE(OCPISchema):
    uid: str
    evse_id: Optional[str] = None
    status: str                             # EVSE Status
    connectors: list[Connector]
    physical_reference: Optional[str] = None
    floor_level: Optional[str] = None
    last_updated: OCPIDateTime


class Location(OCPISchema):
    country_code: str
    party_id: str
    id: str
    publish: bool = True
    name: Optional[str] = None
    address: str
    city: str
    postal_code: Optional[str] = None
    country: str                            # ISO 3166-1 alpha-3
    coordinates: GeoLocation
    evses: list[EVSE] = []
    operator: Optional[BusinessDetails] = None
    time_zone: Optional[str] = None
    last_updated: OCPIDateTime
