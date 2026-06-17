"""OCPI Versions module — the registration entry point.

  GET /ocpi/versions   -> list of supported versions
  GET /ocpi/2.2.1      -> endpoints we expose for 2.2.1

Both require a valid token (Token A during bootstrap, Token C afterwards).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import OCPI_VERSION, config
from ..auth import AuthContext, require_registration_token
from ..enums import InterfaceRole, ModuleID
from ..envelope import ok
from ..schemas.versions import Endpoint, Version, VersionDetails

router = APIRouter(tags=["ocpi-versions"])


@router.get("/versions")
async def list_versions(_auth: AuthContext = Depends(require_registration_token)):
    data = [Version(version=OCPI_VERSION, url=config.version_details_url())]
    return ok(data)


def _endpoints() -> list[Endpoint]:
    S, R = InterfaceRole.SENDER, InterfaceRole.RECEIVER
    spec = [
        (ModuleID.CREDENTIALS, S),
        (ModuleID.CREDENTIALS, R),
        (ModuleID.LOCATIONS, S),
        (ModuleID.SESSIONS, S),
        (ModuleID.CDRS, S),
        (ModuleID.TARIFFS, S),
        (ModuleID.TOKENS, R),
        (ModuleID.COMMANDS, R),
    ]
    return [Endpoint(identifier=mod, role=role, url=config.module_url(mod)) for mod, role in spec]


@router.get(f"/{OCPI_VERSION}")
async def version_details(_auth: AuthContext = Depends(require_registration_token)):
    data = VersionDetails(version=OCPI_VERSION, endpoints=_endpoints())
    return ok(data)
