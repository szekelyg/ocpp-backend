# app/ocpp/ocpp_utils.py
"""Shared OCPP utility functions used across handlers."""
from __future__ import annotations

import os
from typing import Any, Optional

def _min_charge_huf() -> int:
    """
    Üzleti minimum (HUF): ennél kisebb összeget nem vonunk le / nem számlázunk.
    Env-ből felülírható a STRIPE_MIN_HUF változóval (alapértelmezés 500).
    FIGYELEM: a Stripe technikai HUF-minimuma külön ~175 Ft – ez alatti capture-t
    a Stripe elutasít, ezért élesben ne állítsd 175 alá, ha ténylegesen terhelni akarsz.
    """
    v = os.environ.get("STRIPE_MIN_HUF")
    try:
        return int(float(v)) if v else 500
    except (ValueError, TypeError):
        return 500


# Üzleti minimum (HUF) – egyetlen forrás, ne duplikáld! (env: STRIPE_MIN_HUF)
MIN_CHARGE_HUF = _min_charge_huf()


def _as_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip():
            return float(v.strip())
    except Exception:
        return None
    return None


def _as_int(v: Any) -> Optional[int]:
    if isinstance(v, int):
        return v
    f = _as_float(v)
    return int(f) if f is not None else None


def _pick_measurand_sum(
    sampled_values: Any, measurand: str, default_measurand: bool = False
) -> Optional[float]:
    """
    sampledValue listából kivesszük a measurand összegzett értékét.
    Először phase nélkülit keres, majd fázisonként összeadja.

    default_measurand=True esetén a measurand nélküli értékek is illeszkednek:
    OCPP 1.6-ban a measurand kulcs nélküli sampledValue alapból
    "Energy.Active.Import.Register". Enélkül egyes töltők élő energia értékei
    kimaradnának (UI 0 kWh / 0 Ft töltés közben).
    """
    if not isinstance(sampled_values, list):
        return None

    def _matches(sv: dict) -> bool:
        m = sv.get("measurand")
        if m == measurand:
            return True
        return default_measurand and m is None

    for sv in sampled_values:
        if isinstance(sv, dict) and _matches(sv) and not sv.get("phase"):
            return _as_float(sv.get("value"))

    total = 0.0
    found = False
    for sv in sampled_values:
        if isinstance(sv, dict) and _matches(sv):
            val = _as_float(sv.get("value"))
            if val is not None:
                total += val
                found = True

    return total if found else None


def _pick_measurand_phases(sampled_values: Any, measurand: str) -> Optional[dict]:
    """Egy measurand fázisonkénti értékei: {"L1": .., "L2": .., "L3": ..}.

    Csak a ténylegesen jelenlévő fázisokat adja vissza. None, ha a töltő nem
    küld fázisbontást ehhez a measurand-hoz.
    """
    if not isinstance(sampled_values, list):
        return None
    out: dict = {}
    for sv in sampled_values:
        if not isinstance(sv, dict) or sv.get("measurand") != measurand:
            continue
        ph = sv.get("phase")
        if not ph:
            continue
        val = _as_float(sv.get("value"))
        if val is not None:
            out[str(ph)] = val
    return out or None


def _price_huf_per_kwh() -> Optional[float]:
    v = os.environ.get("OCPP_PRICE_HUF_PER_KWH")
    if not v:
        return None
    try:
        x = float(v)
        return x if x >= 0 else None
    except Exception:
        return None


def effective_price_huf_per_kwh(intent=None) -> Optional[float]:
    """
    Per-intent ár-override (ChargingIntent.price_huf_per_kwh), ha van; különben a
    globális env ár. Az intent-et a hívónak már be kell töltenie (async lazy-load tilos).
    """
    if intent is not None:
        p = getattr(intent, "price_huf_per_kwh", None)
        if p is not None:
            try:
                return float(p)
            except (ValueError, TypeError):
                pass
    return _price_huf_per_kwh()


def effective_min_charge_huf(intent=None) -> int:
    """
    Per-intent minimum/capture-override (ChargingIntent.min_charge_huf), ha van;
    különben a globális üzleti minimum (MIN_CHARGE_HUF).
    """
    if intent is not None:
        m = getattr(intent, "min_charge_huf", None)
        if m is not None:
            try:
                return int(m)
            except (ValueError, TypeError):
                pass
    return MIN_CHARGE_HUF
