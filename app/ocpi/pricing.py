"""Shared HUF/VAT helpers for OCPI Tariffs and CDRs.

The internal system prices in GROSS HUF (OCPP_PRICE_HUF_PER_KWH and cost_huf are
VAT-inclusive, mirroring app/services/invoice.py). OCPI price components are
quoted EXCL VAT, so we split here. VAT is the Hungarian 27% (kept in sync with
invoice.py ``_VAT_RATE``).
"""
from __future__ import annotations

from typing import Optional

from .schemas.common import Price

VAT_PERCENT = 27.0
VAT_DIVISOR = 1.0 + VAT_PERCENT / 100.0


def net_from_gross(gross: float, ndigits: int = 4) -> float:
    return round(gross / VAT_DIVISOR, ndigits)


def price_from_gross(gross_huf: Optional[float]) -> Price:
    """Build an OCPI Price {excl_vat, incl_vat} from a gross HUF amount."""
    g = round(float(gross_huf or 0.0), 2)
    return Price(excl_vat=round(g / VAT_DIVISOR, 2), incl_vat=g)
