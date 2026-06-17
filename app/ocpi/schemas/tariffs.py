"""OCPI Tariffs module schemas."""
from __future__ import annotations

from typing import Optional

from .common import OCPISchema, OCPIDateTime, Price, DisplayText


class PriceComponent(OCPISchema):
    type: str                       # TariffDimensionType: ENERGY / FLAT / TIME / PARKING_TIME
    price: float                    # per unit, EXCL VAT
    vat: Optional[float] = None     # VAT percentage, e.g. 27.0
    step_size: int                  # smallest billed unit (Wh for ENERGY, s for TIME)


class TariffRestrictions(OCPISchema):
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    min_kwh: Optional[float] = None
    max_kwh: Optional[float] = None


class TariffElement(OCPISchema):
    price_components: list[PriceComponent]
    restrictions: Optional[TariffRestrictions] = None


class Tariff(OCPISchema):
    country_code: str
    party_id: str
    id: str
    currency: str
    type: Optional[str] = None      # AD_HOC_PAYMENT / REGULAR / ...
    tariff_alt_text: Optional[list[DisplayText]] = None
    elements: list[TariffElement]
    min_price: Optional[Price] = None
    max_price: Optional[Price] = None
    last_updated: OCPIDateTime
