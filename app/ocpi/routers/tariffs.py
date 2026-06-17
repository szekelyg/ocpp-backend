"""OCPI Tariffs module (CPO = Sender).

  GET /ocpi/2.2.1/tariffs            (paginated list — currently one tariff)
  GET /ocpi/2.2.1/tariffs/{tariff_id}

The single tariff is derived from env pricing on the fly (see mappers/tariffs.py).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.db.models import OcpiParty

from .. import OCPI_VERSION, config, status_codes
from ..auth import require_party
from ..envelope import ok
from ..errors import OCPIException
from ..mappers.tariffs import build_default_tariff
from ..pagination import pagination_headers, parse_page

router = APIRouter(prefix=f"/{OCPI_VERSION}/tariffs", tags=["ocpi-tariffs"])


@router.get("")
async def list_tariffs(
    request: Request,
    _party: OcpiParty = Depends(require_party),
    offset: int = 0,
    limit: int = None,  # noqa: RUF013
):
    page = parse_page(offset, limit)
    all_tariffs = [build_default_tariff()]
    total = len(all_tariffs)
    data = all_tariffs[page.offset: page.offset + page.limit]
    return ok(data, headers=pagination_headers(request, page, total))


@router.get("/{tariff_id}")
async def get_tariff(tariff_id: str, _party: OcpiParty = Depends(require_party)):
    if tariff_id != config.default_tariff_id():
        raise OCPIException(status_codes.UNKNOWN_RESOURCE, "Unknown tariff", http_status=404)
    return ok(build_default_tariff())
