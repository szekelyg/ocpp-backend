"""Map a ChargeSession to an OCPI Session.

Local Stripe/QR sessions have no eMSP token, so they get an AD_HOC CdrToken and
AUTH_REQUEST auth method. Roaming sessions (set by the Tokens/Commands modules)
carry the partner's token identity on the row.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.db.models import ChargeSession
from app.ocpp.time_utils import utcnow

from .. import config, enums, ids
from ..pricing import price_from_gross
from ..schemas.sessions import CdrToken, Session


def cdr_token_for_session(cs: ChargeSession) -> CdrToken:
    if cs.ocpi_token_uid:
        return CdrToken(
            country_code=cs.ocpi_country_code or config.country_code(),
            party_id=cs.ocpi_party_id or config.party_id(),
            uid=cs.ocpi_token_uid,
            type=enums.TokenType.RFID,
            contract_id=cs.ocpi_token_uid,
        )
    adhoc = f"AD_HOC-{cs.id}"
    return CdrToken(
        country_code=config.country_code(),
        party_id=config.party_id(),
        uid=adhoc,
        type=enums.TokenType.AD_HOC_USER,
        contract_id=adhoc,
    )


def _location_id(cs: ChargeSession) -> str:
    cp = cs.charge_point
    if cp is not None and cp.location_id is not None:
        return str(cp.location_id)
    return str(cs.charge_point_id)


def _last_updated(cs: ChargeSession) -> datetime:
    return cs.ocpi_last_updated or cs.updated_at or utcnow()


def session_from_orm(cs: ChargeSession) -> Session:
    cp = cs.charge_point
    return Session(
        country_code=config.country_code(),
        party_id=config.party_id(),
        id=cs.ocpi_session_id or str(cs.id),
        start_date_time=cs.started_at,
        end_date_time=cs.finished_at,
        kwh=float(cs.energy_kwh or 0.0),
        cdr_token=cdr_token_for_session(cs),
        auth_method=cs.ocpi_auth_method or enums.AuthMethod.AUTH_REQUEST,
        location_id=_location_id(cs),
        evse_uid=ids.evse_uid(cp) if cp is not None else str(cs.charge_point_id),
        connector_id=ids.DEFAULT_CONNECTOR_ID,
        currency="HUF",
        total_cost=price_from_gross(cs.cost_huf) if cs.cost_huf is not None else None,
        status=enums.session_status(cs),
        last_updated=_last_updated(cs),
    )
