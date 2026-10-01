"""Vevő adóalanyisága a Számlázz.hu-számlán (2026-10-01): céges számla magyar adószámmal → 1, különben -1."""
from app.services.invoice import _tax_subject


def test_ceges_magyar_adoszammal_afa_alany():
    assert _tax_subject("business", "12345678-2-42") == 1
    assert _tax_subject("business", "12345678242") == 1


def test_maganszemely_vagy_hianyzo_adoszam():
    assert _tax_subject("personal", "12345678-2-42") == -1
    assert _tax_subject(None, None) == -1
    assert _tax_subject("business", None) == -1
    assert _tax_subject("business", "") == -1


def test_nem_magyar_adoszam_nem_ismert():
    assert _tax_subject("business", "DE123456789") == -1
