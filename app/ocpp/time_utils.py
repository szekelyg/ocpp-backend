# app/ocpp/time_utils.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc_now_z() -> str:
    return utcnow().isoformat().replace("+00:00", "Z")


def parse_ocpp_timestamp(ts: Any) -> datetime:
    """
    OCPP timestamp lehet "Z" vagy +00:00; mindent UTC datetime-re hozunk.
    """
    if not isinstance(ts, str) or not ts.strip():
        return utcnow()

    s = ts.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return utcnow()