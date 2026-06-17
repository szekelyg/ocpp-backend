"""Map internal Location/ChargePoint rows to OCPI Location/EVSE/Connector.

The internal model is flat: one ChargePoint == one EVSE == one Connector. The
single ``address_text`` field is best-effort split into address/city/postal_code
(Hungarian format); unparsed values fall back to config defaults.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Optional

from app.api.routers.charge_points import compute_status
from app.db.models import ChargePoint, Location as LocationORM

from .. import config, enums, ids
from ..schemas.common import BusinessDetails, GeoLocation
from ..schemas.locations import Connector, EVSE, Location

# Hungarian address: "1234 Budapest, Vak Bottyán u. 1." -> postal, city, street.
_HU_ADDR = re.compile(r"^\s*(\d{4})\s+([^,]+?)[,\s]+(.*\S)\s*$")


def _parse_hu_address(text: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (street, city, postal_code); any may be None when unparseable."""
    if not text:
        return None, None, None
    m = _HU_ADDR.match(text)
    if m:
        return m.group(3).strip(), m.group(2).strip(), m.group(1)
    return text.strip(), None, None


def _fmt_coord(v: Optional[float]) -> str:
    return f"{float(v):.6f}" if v is not None else "0.000000"


def _voltage_amperage(power_type: str, kw: Optional[float]) -> tuple[int, int]:
    if power_type == enums.PowerType.DC:
        v, a = 500, (kw * 1000 / 500 if kw else 125)
    elif power_type == enums.PowerType.AC_1_PHASE:
        v, a = 230, (kw * 1000 / 230 if kw else 16)
    else:  # AC_3_PHASE
        v, a = 400, (kw * 1000 / (math.sqrt(3) * 400) if kw else 32)
    return v, max(int(round(a)), 1)


def _last_updated(*candidates) -> datetime:
    for c in candidates:
        if c is not None:
            return c
    from app.ocpp.time_utils import utcnow
    return utcnow()


def connector_from_cp(cp: ChargePoint) -> Connector:
    standard = enums.connector_standard(cp.connector_type)
    power = enums.power_type(standard, cp.max_power_kw)
    voltage, amperage = _voltage_amperage(power, cp.max_power_kw)
    return Connector(
        id=ids.DEFAULT_CONNECTOR_ID,
        standard=standard,
        format=enums.connector_format(power),
        power_type=power,
        max_voltage=voltage,
        max_amperage=amperage,
        max_electric_power=int(cp.max_power_kw * 1000) if cp.max_power_kw else None,
        tariff_ids=[config.default_tariff_id()],
        last_updated=_last_updated(cp.ocpi_last_updated, cp.updated_at),
    )


def evse_from_cp(cp: ChargePoint) -> EVSE:
    return EVSE(
        uid=ids.evse_uid(cp),
        evse_id=ids.evse_id(cp.id),
        status=enums.evse_status(compute_status(cp)),
        connectors=[connector_from_cp(cp)],
        physical_reference=cp.serial_number or None,
        last_updated=_last_updated(cp.ocpi_last_updated, cp.updated_at),
    )


def location_from_orm(loc: LocationORM) -> Location:
    street, city, postal = _parse_hu_address(loc.address_text)
    evses = [evse_from_cp(cp) for cp in (loc.charge_points or [])]
    return Location(
        country_code=(loc.country_code or config.country_code()),
        party_id=(loc.party_id or config.party_id()),
        id=ids.location_id(loc.id),
        publish=True,
        name=loc.name,
        address=street or loc.address_text or loc.name or "N/A",
        city=city or config.default_city(),
        postal_code=postal,
        country=config.country_alpha3(),
        coordinates=GeoLocation(latitude=_fmt_coord(loc.latitude), longitude=_fmt_coord(loc.longitude)),
        evses=evses,
        operator=BusinessDetails(**config.business_details()),
        time_zone=loc.time_zone or config.time_zone(),
        last_updated=_last_updated(loc.ocpi_last_updated, loc.updated_at),
    )


def find_evse(loc: LocationORM, evse_uid: str) -> Optional[ChargePoint]:
    for cp in (loc.charge_points or []):
        if ids.evse_uid(cp) == evse_uid:
            return cp
    return None
