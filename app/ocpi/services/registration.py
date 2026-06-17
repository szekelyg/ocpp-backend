"""OCPI Credentials registration handshake (Token A -> B -> C).

Flow when a partner POSTs their credentials (authenticated with our Token A):
  1. They send Token B + their versions URL + their roles.
  2. We GET their versions with Token B, pick 2.2.1, GET its endpoints.
  3. We generate Token C, persist the party (token_outgoing=B, token_incoming=C).
  4. We return our credentials object carrying Token C.

From then on the partner authenticates to us with Token C.
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OcpiParty
from app.ocpp.time_utils import utcnow

from .. import OCPI_VERSION, config, push, status_codes
from ..errors import OCPIException
from ..schemas.common import BusinessDetails
from ..schemas.credentials import Credentials, CredentialsInput, CredentialsRole

logger = logging.getLogger("ocpi")


def our_cpo_role() -> CredentialsRole:
    return CredentialsRole(
        role="CPO",
        business_details=BusinessDetails(**config.business_details()),
        party_id=config.party_id(),
        country_code=config.country_code(),
    )


def build_our_credentials(token_for_partner: str) -> Credentials:
    """Our credentials object: ``token`` is what the partner uses to call us."""
    return Credentials(
        token=token_for_partner,
        url=config.versions_url(),
        roles=[our_cpo_role()],
    )


async def _resolve_partner_endpoints(versions_url: str, token_b: str) -> tuple[str, list]:
    """Return (version_details_url, endpoints) for the partner's 2.2.1 version."""
    try:
        versions = await push.get_json(versions_url, token_b)
    except push.OCPIClientError as e:
        logger.warning(f"registration: cannot fetch partner versions {versions_url}: {e}")
        raise OCPIException(status_codes.UNABLE_TO_USE_CLIENT_API, "Could not fetch partner versions")

    details_url: Optional[str] = None
    for v in versions or []:
        if isinstance(v, dict) and v.get("version") == OCPI_VERSION:
            details_url = v.get("url")
            break
    if not details_url:
        raise OCPIException(status_codes.UNSUPPORTED_VERSION, f"Partner does not support {OCPI_VERSION}")

    try:
        details = await push.get_json(details_url, token_b)
    except push.OCPIClientError as e:
        logger.warning(f"registration: cannot fetch partner version details {details_url}: {e}")
        raise OCPIException(status_codes.UNABLE_TO_USE_CLIENT_API, "Could not fetch partner endpoints")

    endpoints = (details or {}).get("endpoints") or []
    if not endpoints:
        raise OCPIException(status_codes.NO_MATCHING_ENDPOINTS, "Partner exposed no endpoints")
    return details_url, endpoints


def _primary_role(creds: CredentialsInput) -> CredentialsRole:
    if not creds.roles:
        raise OCPIException(status_codes.INVALID_PARAMETERS, "Missing roles in credentials")
    return creds.roles[0]


async def find_party(db: AsyncSession, role: str, country_code: str, party_id: str) -> Optional[OcpiParty]:
    return (
        await db.execute(
            select(OcpiParty).where(
                OcpiParty.role == role,
                OcpiParty.country_code == country_code.upper(),
                OcpiParty.party_id == party_id.upper(),
            )
        )
    ).scalar_one_or_none()


async def register_or_update(
    db: AsyncSession,
    creds: CredentialsInput,
    *,
    existing: Optional[OcpiParty] = None,
) -> tuple[OcpiParty, Credentials]:
    """Perform the handshake; create or refresh the party; return (party, our creds)."""
    role = _primary_role(creds)
    details_url, endpoints = await _resolve_partner_endpoints(creds.url, creds.token)

    token_c = secrets.token_urlsafe(32)
    party = existing or await find_party(db, role.role, role.country_code, role.party_id)
    if party is None:
        party = OcpiParty(
            role=role.role,
            country_code=role.country_code.upper(),
            party_id=role.party_id.upper(),
        )
        db.add(party)

    party.business_name = role.business_details.name
    party.business_website = role.business_details.website
    party.business_logo_url = role.business_details.logo.url if role.business_details.logo else None
    party.versions_url = creds.url
    party.version_details_url = details_url
    party.endpoints = endpoints
    party.token_outgoing = creds.token   # Token B (us -> them)
    party.token_incoming = token_c       # Token C (them -> us)
    party.status = "REGISTERED"
    party.registered_at = utcnow()

    await db.commit()
    await db.refresh(party)
    return party, build_our_credentials(token_c)


async def unregister(db: AsyncSession, party: OcpiParty) -> None:
    await db.delete(party)
    await db.commit()
