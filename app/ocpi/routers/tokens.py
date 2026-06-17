"""OCPI Tokens module (CPO = Receiver).

  GET   /ocpi/2.2.1/tokens/{country_code}/{party_id}/{token_uid}[?type=]
  PUT   /ocpi/2.2.1/tokens/{country_code}/{party_id}/{token_uid}[?type=]
  PATCH /ocpi/2.2.1/tokens/{country_code}/{party_id}/{token_uid}[?type=]

(The ``authorize`` endpoint is part of the eMSP *Sender* interface, not the CPO
Receiver, so it is intentionally not hosted here.)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import OcpiParty

from .. import OCPI_VERSION, enums, status_codes
from ..auth import require_party
from ..envelope import ok
from ..errors import OCPIException
from ..schemas.tokens import Token
from ..services import token_cache

router = APIRouter(prefix=f"/{OCPI_VERSION}/tokens", tags=["ocpi-tokens"])


@router.get("/{country_code}/{party_id}/{token_uid}")
async def get_token(
    country_code: str,
    party_id: str,
    token_uid: str,
    type: str = enums.TokenType.RFID,
    db: AsyncSession = Depends(get_db),
    _party: OcpiParty = Depends(require_party),
):
    row = await token_cache.get_token(db, country_code, party_id, token_uid, type)
    if row is None:
        raise OCPIException(status_codes.UNKNOWN_RESOURCE, "Unknown token", http_status=404)
    return ok(token_cache.token_orm_to_schema(row))


@router.put("/{country_code}/{party_id}/{token_uid}")
async def put_token(
    country_code: str,
    party_id: str,
    token_uid: str,
    request: Request,
    type: str = enums.TokenType.RFID,
    db: AsyncSession = Depends(get_db),
    _party: OcpiParty = Depends(require_party),
):
    try:
        token = Token(**(await request.json()))
    except (ValidationError, TypeError, ValueError) as e:
        raise OCPIException(status_codes.INVALID_PARAMETERS, f"Invalid token object: {e}")
    await token_cache.upsert_token(db, country_code, party_id, token_uid, type, token)
    return ok()


@router.patch("/{country_code}/{party_id}/{token_uid}")
async def patch_token(
    country_code: str,
    party_id: str,
    token_uid: str,
    request: Request,
    type: str = enums.TokenType.RFID,
    db: AsyncSession = Depends(get_db),
    _party: OcpiParty = Depends(require_party),
):
    try:
        patch = await request.json()
        if not isinstance(patch, dict):
            raise ValueError("body must be an object")
    except ValueError as e:
        raise OCPIException(status_codes.INVALID_PARAMETERS, f"Invalid patch body: {e}")
    row = await token_cache.patch_token(db, country_code, party_id, token_uid, type, patch)
    if row is None:
        raise OCPIException(status_codes.UNKNOWN_RESOURCE, "Unknown token", http_status=404)
    return ok()
