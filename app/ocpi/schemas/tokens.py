"""OCPI Tokens module schemas (CPO = Receiver)."""
from __future__ import annotations

from typing import Optional

from .common import OCPISchema, OCPIDateTime, DisplayText


class EnergyContract(OCPISchema):
    supplier_name: str
    contract_id: Optional[str] = None


class Token(OCPISchema):
    country_code: str
    party_id: str
    uid: str
    type: str                       # TokenType
    contract_id: str
    visual_number: Optional[str] = None
    issuer: str
    group_id: Optional[str] = None
    valid: bool
    whitelist: str                  # WhitelistType
    language: Optional[str] = None
    default_profile_type: Optional[str] = None
    energy_contract: Optional[EnergyContract] = None
    last_updated: OCPIDateTime


class LocationReferences(OCPISchema):
    location_id: str
    evse_uids: Optional[list[str]] = None


class AuthorizationInfo(OCPISchema):
    allowed: str                    # AllowedType
    token: Token
    location: Optional[LocationReferences] = None
    authorization_reference: Optional[str] = None
    info: Optional[DisplayText] = None
