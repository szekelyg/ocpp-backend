"""OCPI response envelope.

Every OCPI response body is wrapped as::

    {"data": ..., "status_code": 1000, "status_message": "Success",
     "timestamp": "2026-06-17T08:55:00Z"}

The HTTP status is almost always 200 — transport success is separate from the
OCPI-level ``status_code`` (see status_codes.py). Use :func:`ok` / :func:`error`
to build responses, and :func:`format_ocpi_datetime` everywhere a datetime is
serialized so the format stays OCPI-compliant (UTC, ``Z`` suffix, seconds).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import status_codes


def format_ocpi_datetime(dt: datetime) -> str:
    """OCPI DateTime: RFC 3339, UTC, ``Z`` suffix, no microseconds.

    Naive datetimes are assumed UTC (the codebase stores tz-aware UTC, but
    legacy rows may be naive).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def utcnow_str() -> str:
    return format_ocpi_datetime(datetime.now(timezone.utc))


def parse_ocpi_datetime(value: str | None) -> datetime | None:
    """Parse an OCPI DateTime query param (accepts trailing ``Z``)."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _jsonable(data: Any) -> Any:
    """Convert pydantic models / lists to JSON-native structures.

    ``mode="json"`` makes pydantic emit datetimes as ISO strings; our schemas
    use a field serializer (see schemas/common.py) so those land in OCPI format.
    ``exclude_none`` keeps optional OCPI fields out of the payload entirely.
    """
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json", exclude_none=True)
    if isinstance(data, (list, tuple)):
        return [_jsonable(x) for x in data]
    return data


def ok(
    data: Any = None,
    *,
    status_code: int = status_codes.SUCCESS,
    status_message: str | None = None,
    http_status: int = 200,
    headers: dict | None = None,
) -> JSONResponse:
    body = {
        "status_code": status_code,
        "status_message": status_message or status_codes.default_message(status_code),
        "timestamp": utcnow_str(),
    }
    if data is not None:
        body["data"] = _jsonable(data)
    return JSONResponse(content=body, status_code=http_status, headers=headers)


def error(
    status_code: int,
    status_message: str | None = None,
    *,
    http_status: int = 200,
    headers: dict | None = None,
) -> JSONResponse:
    body = {
        "status_code": status_code,
        "status_message": status_message or status_codes.default_message(status_code),
        "timestamp": utcnow_str(),
    }
    return JSONResponse(content=body, status_code=http_status, headers=headers)
