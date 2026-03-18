# app/ocpp/ocpp_utils.py
"""Shared OCPP utility functions used across handlers."""
from __future__ import annotations

import os
from typing import Any, Optional


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


def _pick_measurand_sum(sampled_values: Any, measurand: str) -> Optional[float]:
    """
    sampledValue listából kivesszük a measurand összegzett értékét.
    Először phase nélkülit keres, majd fázisonként összeadja.
    """
    if not isinstance(sampled_values, list):
        return None

    for sv in sampled_values:
        if isinstance(sv, dict) and sv.get("measurand") == measurand and not sv.get("phase"):
            return _as_float(sv.get("value"))

    total = 0.0
    found = False
    for sv in sampled_values:
        if isinstance(sv, dict) and sv.get("measurand") == measurand:
            val = _as_float(sv.get("value"))
            if val is not None:
                total += val
                found = True

    return total if found else None


def _price_huf_per_kwh() -> Optional[float]:
    v = os.environ.get("OCPP_PRICE_HUF_PER_KWH")
    if not v:
        return None
    try:
        x = float(v)
        return x if x >= 0 else None
    except Exception:
        return None
