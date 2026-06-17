"""OCPI ``Authorization: Token <base64>`` authentication.

OCPI 2.2.1 base64-encodes the token in the header; we decode it but also accept
the raw token (some partners / OCPI 2.2 send it un-encoded). Tokens are matched
with constant-time comparison against:

  * Token A (settings.ocpi_token_a) — bootstrap only (versions + POST credentials)
  * ocpi_parties.token_incoming (Token C) — registered partners, all modules

Fail-closed: if OCPI isn't configured (disabled or no Token A) every protected
endpoint returns 503, mirroring the admin auth posture.
"""
from __future__ import annotations

import base64
import binascii
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.db.models import OcpiParty

from . import config, status_codes
from .errors import OCPIException


@dataclass
class AuthContext:
    """Result of a successful auth: either Token A (bootstrap) or a party."""
    is_token_a: bool
    party: Optional[OcpiParty] = None


def _parse_authorization(authorization: Optional[str]) -> Optional[str]:
    """Extract the credential after the ``Token`` scheme (case-insensitive)."""
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "token":
        return None
    return parts[1].strip()


def _candidate_tokens(credential: str) -> list[str]:
    """Both the base64-decoded and the raw form, so we accept either encoding."""
    candidates = [credential]
    try:
        decoded = base64.b64decode(credential, validate=True).decode("utf-8")
        if decoded and decoded != credential:
            candidates.append(decoded)
    except (binascii.Error, ValueError, UnicodeDecodeError):
        pass
    return candidates


def _matches(candidates: list[str], stored: Optional[str]) -> bool:
    if not stored:
        return False
    return any(secrets.compare_digest(c, stored) for c in candidates)


async def _match_party(db: AsyncSession, candidates: list[str]) -> Optional[OcpiParty]:
    """Find a registered party whose Token C matches one of the candidates.

    Loads the small parties set and compares in constant time (avoids leaking
    which tokens exist via a DB-lookup short-circuit).
    """
    rows = (await db.execute(select(OcpiParty))).scalars().all()
    for party in rows:
        if party.status == "REGISTERED" and _matches(candidates, party.token_incoming):
            return party
    return None


def _ensure_enabled() -> None:
    if not config.ocpi_enabled():
        raise OCPIException(
            status_codes.SERVER_ERROR,
            "OCPI not configured",
            http_status=503,
        )


def _unauthorized() -> OCPIException:
    return OCPIException(
        status_codes.CLIENT_ERROR,
        "Missing or invalid authorization token",
        http_status=401,
        headers={"WWW-Authenticate": "Token"},
    )


async def require_registration_token(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """Accept Token A (bootstrap) OR a registered party's Token C.

    Used by versions, version details and the credentials endpoints.
    """
    _ensure_enabled()
    credential = _parse_authorization(authorization)
    if not credential:
        raise _unauthorized()
    candidates = _candidate_tokens(credential)

    if _matches(candidates, settings.ocpi_token_a):
        return AuthContext(is_token_a=True)

    party = await _match_party(db, candidates)
    if party is not None:
        return AuthContext(is_token_a=False, party=party)

    raise _unauthorized()


async def require_party(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> OcpiParty:
    """Accept only a fully-registered party's Token C. Used by all data modules."""
    _ensure_enabled()
    credential = _parse_authorization(authorization)
    if not credential:
        raise _unauthorized()
    party = await _match_party(db, _candidate_tokens(credential))
    if party is None:
        raise _unauthorized()
    return party
