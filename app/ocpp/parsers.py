# app/ocpp/parsers.py
from __future__ import annotations

from typing import Any

from app.ocpp.ocpp_utils import _as_float, _as_int, _pick_measurand_sum  # noqa: F401 (re-export)


def _normalize_cp_status(ocpp_status: Any) -> str:
    if isinstance(ocpp_status, str) and ocpp_status.strip():
        return ocpp_status.strip().lower()
    return "unknown"