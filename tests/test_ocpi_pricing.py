"""Unit tests for the HUF/VAT split shared by Tariffs and CDRs (no DB)."""
from app.ocpi import pricing


def test_net_from_gross():
    # 170 HUF gross per kWh -> net excl 27% VAT (rounded to 4 decimals)
    assert pricing.net_from_gross(170.0) == round(170 / 1.27, 4)


def test_price_from_gross_split():
    p = pricing.price_from_gross(1700.0)
    assert p.incl_vat == 1700.0
    assert abs(p.excl_vat - round(1700 / 1.27, 2)) < 1e-9
    # gross = net + 27% VAT (within rounding)
    assert abs(p.excl_vat * 1.27 - p.incl_vat) < 0.01


def test_price_from_gross_none_is_zero():
    p = pricing.price_from_gross(None)
    assert p.incl_vat == 0.0
    assert p.excl_vat == 0.0
