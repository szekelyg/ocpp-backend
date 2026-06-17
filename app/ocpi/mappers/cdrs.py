"""Build an OCPI CDR from a finished ChargeSession, and rebuild it from storage.

The CDR is an immutable snapshot: ``build_cdr_from_session`` captures the price,
energy and VAT split at completion time; ``cdr_orm_to_schema`` re-materializes a
stored ``OcpiCdr`` row for the GET endpoints.
"""
from __future__ import annotations

from datetime import timezone

from app.db.models import ChargeSession, OcpiCdr
from app.ocpp.time_utils import utcnow

from .. import config, enums, ids
from ..pricing import price_from_gross
from ..schemas.cdrs import CDR, CdrLocation
from ..schemas.common import GeoLocation
from ..schemas.sessions import CdrDimension, ChargingPeriod
from .locations import _fmt_coord, _parse_hu_address
from .sessions import cdr_token_for_session
from .tariffs import build_default_tariff


def _duration_hours(cs: ChargeSession) -> float:
    if not cs.started_at or not cs.finished_at:
        return 0.0
    start = cs.started_at if cs.started_at.tzinfo else cs.started_at.replace(tzinfo=timezone.utc)
    end = cs.finished_at if cs.finished_at.tzinfo else cs.finished_at.replace(tzinfo=timezone.utc)
    return max(0.0, (end - start).total_seconds() / 3600.0)


def _cdr_location(cs: ChargeSession) -> CdrLocation:
    cp = cs.charge_point
    loc = cp.location if cp is not None else None
    standard = enums.connector_standard(cp.connector_type if cp else None)
    power = enums.power_type(standard, cp.max_power_kw if cp else None)
    street, city, postal = _parse_hu_address(loc.address_text if loc else None)
    return CdrLocation(
        id=str(loc.id) if loc else str(cs.charge_point_id),
        name=loc.name if loc else None,
        address=street or (loc.address_text if loc else None) or "N/A",
        city=city or config.default_city(),
        postal_code=postal,
        country=config.country_alpha3(),
        coordinates=GeoLocation(
            latitude=_fmt_coord(loc.latitude if loc else None),
            longitude=_fmt_coord(loc.longitude if loc else None),
        ),
        evse_uid=ids.evse_uid(cp) if cp is not None else str(cs.charge_point_id),
        evse_id=ids.evse_id(cp.id) if cp is not None else f"E{cs.charge_point_id}",
        connector_id=ids.DEFAULT_CONNECTOR_ID,
        connector_standard=standard,
        connector_format=enums.connector_format(power),
        connector_power_type=power,
    )


def build_cdr_from_session(cs: ChargeSession) -> CDR:
    energy = float(cs.energy_kwh or 0.0)
    hours = _duration_hours(cs)
    period = ChargingPeriod(
        start_date_time=cs.started_at,
        dimensions=[
            CdrDimension(type=enums.CdrDimensionType.ENERGY, volume=energy),
            CdrDimension(type=enums.CdrDimensionType.TIME, volume=hours),
        ],
        tariff_id=config.default_tariff_id(),
    )
    return CDR(
        country_code=config.country_code(),
        party_id=config.party_id(),
        id=str(cs.id),
        start_date_time=cs.started_at,
        end_date_time=cs.finished_at or utcnow(),
        session_id=cs.ocpi_session_id or str(cs.id),
        cdr_token=cdr_token_for_session(cs),
        auth_method=cs.ocpi_auth_method or enums.AuthMethod.AUTH_REQUEST,
        cdr_location=_cdr_location(cs),
        currency="HUF",
        tariffs=[build_default_tariff()],
        charging_periods=[period],
        total_cost=price_from_gross(cs.cost_huf),
        total_energy=energy,
        total_time=hours,
        invoice_reference_id=cs.invoice_number,
        last_updated=utcnow(),
    )


def cdr_orm_to_schema(row: OcpiCdr) -> CDR:
    """Rebuild a CDR object from a stored snapshot row (sub-objects are JSON)."""
    return CDR(
        country_code=row.country_code,
        party_id=row.party_id,
        id=row.cdr_id,
        start_date_time=row.start_date_time,
        end_date_time=row.end_date_time or row.start_date_time,
        session_id=str(row.session_id) if row.session_id is not None else None,
        cdr_token=row.cdr_token,
        auth_method=row.auth_method,
        cdr_location=row.cdr_location,
        currency=row.currency,
        tariffs=row.tariffs or [],
        charging_periods=row.charging_periods or [],
        total_cost=row.total_cost,
        total_energy=row.total_energy,
        total_time=row.total_time,
        invoice_reference_id=row.invoice_reference_id,
        last_updated=row.last_updated,
    )
