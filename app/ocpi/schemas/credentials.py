"""OCPI Credentials module schemas (registration handshake)."""
from __future__ import annotations

from typing import Optional

from .common import OCPISchema, BusinessDetails


class CredentialsRole(OCPISchema):
    role: str                       # CPO / EMSP / HUB ...
    business_details: BusinessDetails
    party_id: str                   # CiString(3)
    country_code: str               # CiString(2)


class Credentials(OCPISchema):
    """Sent in both directions during the A->B->C token exchange.

    ``token`` is the token the *receiver of this object* must use to call the
    *sender of this object*.
    """
    token: str
    url: str                        # the sender's versions endpoint
    roles: list[CredentialsRole]


class CredentialsInput(OCPISchema):
    """Partner-supplied credentials on POST/PUT (lenient parsing)."""
    token: str
    url: str
    roles: Optional[list[CredentialsRole]] = None
