"""eMSP token cache (CPO = Receiver of the Tokens module).

eMSPs PUT/PATCH their tokens here; we store them so a token presented at a
charger can be validated against the cache + whitelist without a round-trip.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OcpiToken
from app.ocpp.time_utils import utcnow

from ..schemas.tokens import Token


async def get_token(db: AsyncSession, country_code: str, party_id: str, uid: str, token_type: str) -> Optional[OcpiToken]:
    return (
        await db.execute(
            select(OcpiToken).where(
                OcpiToken.country_code == country_code.upper(),
                OcpiToken.party_id == party_id.upper(),
                OcpiToken.uid == uid,
                OcpiToken.type == token_type,
            )
        )
    ).scalar_one_or_none()


async def upsert_token(db: AsyncSession, country_code: str, party_id: str, uid: str, token_type: str, token: Token) -> OcpiToken:
    row = await get_token(db, country_code, party_id, uid, token_type)
    if row is None:
        row = OcpiToken(country_code=country_code.upper(), party_id=party_id.upper(), uid=uid, type=token_type)
        db.add(row)
    row.contract_id = token.contract_id
    row.issuer = token.issuer
    row.valid = token.valid
    row.whitelist = token.whitelist
    row.visual_number = token.visual_number
    row.group_id = token.group_id
    row.language = token.language
    row.default_profile_type = token.default_profile_type
    row.energy_contract = token.energy_contract.model_dump(mode="json", exclude_none=True) if token.energy_contract else None
    row.raw = token.model_dump(mode="json", exclude_none=True)
    row.last_updated = utcnow()
    await db.commit()
    await db.refresh(row)
    return row


async def patch_token(db: AsyncSession, country_code: str, party_id: str, uid: str, token_type: str, patch: dict) -> Optional[OcpiToken]:
    row = await get_token(db, country_code, party_id, uid, token_type)
    if row is None:
        return None
    _COLUMNS = {
        "contract_id", "issuer", "valid", "whitelist", "visual_number",
        "group_id", "language", "default_profile_type",
    }
    for key, value in patch.items():
        if key in _COLUMNS:
            setattr(row, key, value)
        elif key == "energy_contract":
            row.energy_contract = value
    merged = dict(row.raw or {})
    merged.update(patch)
    row.raw = merged
    row.last_updated = utcnow()
    await db.commit()
    await db.refresh(row)
    return row


def token_orm_to_schema(row: OcpiToken) -> Token:
    return Token(
        country_code=row.country_code,
        party_id=row.party_id,
        uid=row.uid,
        type=row.type,
        contract_id=row.contract_id,
        visual_number=row.visual_number,
        issuer=row.issuer or "",
        group_id=row.group_id,
        valid=bool(row.valid),
        whitelist=row.whitelist,
        language=row.language,
        default_profile_type=row.default_profile_type,
        energy_contract=row.energy_contract,
        last_updated=row.last_updated,
    )
