# app/ocpp/parsers.py
from __future__ import annotations

from typing import Any, Optional


def extract_cp_id_from_boot(payload: dict) -> Optional[str]:
    cp_id = payload.get("chargeBoxSerialNumber") or payload.get("chargePointSerialNumber")
    if isinstance(cp_id, str) and cp_id.strip():
        return cp_id.strip()
    return None


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
    """
    if not isinstance(sampled_values, list):
        return None

    # 1) összesített (phase nélkül)
    for sv in sampled_values:
        if isinstance(sv, dict) and sv.get("measurand") == measurand and not sv.get("phase"):
            return _as_float(sv.get("value"))

    # 2) fázisonként összeadjuk
    total = 0.0
    found = False
    for sv in sampled_values:
        if isinstance(sv, dict) and sv.get("measurand") == measurand:
            val = _as_float(sv.get("value"))
            if val is not None:
                total += val
                found = True

    return total if found else None


def _normalize_cp_status(ocpp_status: Any) -> str:
    if isinstance(ocpp_status, str) and ocpp_status.strip():
        return ocpp_status.strip().lower()
    return "unknown"