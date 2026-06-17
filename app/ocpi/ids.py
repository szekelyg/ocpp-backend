"""OCPI identifier formatting/parsing.

Builds the eMI3-style EVSE ID (``HU*ENF*E1``) and the OCPI object ids derived
from internal primary keys. Keeping this in one place lets the routers reverse
a path param back to an internal row.
"""
from __future__ import annotations

from . import config


def location_id(internal_id: int) -> str:
    """OCPI Location.id (CiString(36)). We use the internal PK as a string."""
    return str(internal_id)


def parse_location_id(ocpi_id: str) -> int | None:
    try:
        return int(ocpi_id)
    except (ValueError, TypeError):
        return None


def evse_uid(charge_point) -> str:
    """Stable EVSE.uid: the stored ocpi_evse_uid, falling back to ocpp_id."""
    return getattr(charge_point, "ocpi_evse_uid", None) or str(charge_point.ocpp_id)


def evse_id(internal_id: int) -> str:
    """eMI3 EVSE ID, e.g. ``HU*ENF*E1`` (sep configurable)."""
    sep = config.evse_id_separator()
    return f"{config.country_code()}{sep}{config.party_id()}{sep}E{internal_id}"


# A flat ChargePoint has exactly one connector; we always use connector id "1".
DEFAULT_CONNECTOR_ID = "1"
