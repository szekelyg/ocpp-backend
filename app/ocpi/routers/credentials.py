"""OCPI Credentials & Registration module.

  GET    /ocpi/2.2.1/credentials  -> our credentials (token the partner uses)
  POST   /ocpi/2.2.1/credentials  -> initial registration (Token A) -> returns Token C
  PUT    /ocpi/2.2.1/credentials  -> update/rotate an existing registration (Token C)
  DELETE /ocpi/2.2.1/credentials  -> unregister (Token C)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import OcpiParty

from .. import OCPI_VERSION, status_codes
from ..auth import AuthContext, require_party, require_registration_token
from ..envelope import ok
from ..errors import OCPIException
from ..schemas.credentials import CredentialsInput
from ..services import registration

router = APIRouter(prefix=f"/{OCPI_VERSION}/credentials", tags=["ocpi-credentials"])


async def _parse_body(request: Request) -> CredentialsInput:
    try:
        raw = await request.json()
    except Exception:
        raise OCPIException(status_codes.INVALID_PARAMETERS, "Invalid JSON body")
    try:
        return CredentialsInput(**raw)
    except (ValidationError, TypeError) as e:
        raise OCPIException(status_codes.INVALID_PARAMETERS, f"Invalid credentials object: {e}")


@router.get("")
async def get_credentials(party: OcpiParty = Depends(require_party)):
    """Return our credentials carrying the token THIS party uses to call us."""
    return ok(registration.build_our_credentials(party.token_incoming))


@router.post("")
async def post_credentials(
    request: Request,
    auth: AuthContext = Depends(require_registration_token),
    db: AsyncSession = Depends(get_db),
):
    creds = await _parse_body(request)
    role = registration._primary_role(creds)
    existing = await registration.find_party(db, role.role, role.country_code, role.party_id)
    if existing is not None and existing.status == "REGISTERED":
        raise OCPIException(
            status_codes.NOT_ENOUGH_INFORMATION,
            "Already registered — use PUT to update credentials",
            http_status=405,
        )
    _party, our_creds = await registration.register_or_update(db, creds, existing=existing)
    return ok(our_creds)


@router.put("")
async def put_credentials(
    request: Request,
    party: OcpiParty = Depends(require_party),
    db: AsyncSession = Depends(get_db),
):
    creds = await _parse_body(request)
    _party, our_creds = await registration.register_or_update(db, creds, existing=party)
    return ok(our_creds)


@router.delete("")
async def delete_credentials(
    party: OcpiParty = Depends(require_party),
    db: AsyncSession = Depends(get_db),
):
    await registration.unregister(db, party)
    return ok()
