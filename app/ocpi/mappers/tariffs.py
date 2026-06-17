"""Build the single OCPI Tariff from the flat env pricing.

Pricing is flat per-kWh (OCPP_PRICE_HUF_PER_KWH, gross HUF) with a minimum
charge (STRIPE_MIN_HUF, gross). We expose one ENERGY price component (excl VAT,
vat=27) plus min_price.
"""
from __future__ import annotations

from app.ocpp.ocpp_utils import MIN_CHARGE_HUF, effective_price_huf_per_kwh
from app.ocpp.time_utils import utcnow

from .. import config, enums
from ..pricing import VAT_PERCENT, net_from_gross, price_from_gross
from ..schemas.tariffs import PriceComponent, Tariff, TariffElement


def build_default_tariff() -> Tariff:
    gross_per_kwh = effective_price_huf_per_kwh() or 0.0
    energy = PriceComponent(
        type=enums.TariffDimensionType.ENERGY,
        price=net_from_gross(gross_per_kwh),
        vat=VAT_PERCENT,
        step_size=1,            # 1 Wh
    )
    return Tariff(
        country_code=config.country_code(),
        party_id=config.party_id(),
        id=config.default_tariff_id(),
        currency="HUF",
        type="AD_HOC_PAYMENT",
        elements=[TariffElement(price_components=[energy])],
        min_price=price_from_gross(MIN_CHARGE_HUF),
        last_updated=utcnow(),
    )
