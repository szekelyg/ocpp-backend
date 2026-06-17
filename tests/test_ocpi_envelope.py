"""Unit tests for the OCPI response envelope (no DB)."""
import json
from datetime import datetime, timezone

from app.ocpi import envelope, status_codes


def _body(resp):
    return json.loads(bytes(resp.body))


def test_format_ocpi_datetime_z_suffix_no_micros():
    dt = datetime(2026, 6, 17, 8, 55, 0, 123456, tzinfo=timezone.utc)
    assert envelope.format_ocpi_datetime(dt) == "2026-06-17T08:55:00Z"


def test_format_ocpi_datetime_naive_assumed_utc():
    dt = datetime(2026, 1, 2, 3, 4, 5)
    assert envelope.format_ocpi_datetime(dt) == "2026-01-02T03:04:05Z"


def test_ok_envelope_shape():
    resp = envelope.ok({"hello": "world"})
    body = _body(resp)
    assert body["status_code"] == status_codes.SUCCESS
    assert body["status_message"] == "Success"
    assert body["data"] == {"hello": "world"}
    assert body["timestamp"].endswith("Z")
    assert resp.status_code == 200


def test_ok_without_data_omits_data_key():
    body = _body(envelope.ok())
    assert "data" not in body
    assert body["status_code"] == status_codes.SUCCESS


def test_error_envelope():
    resp = envelope.error(status_codes.UNKNOWN_RESOURCE, http_status=404)
    body = _body(resp)
    assert body["status_code"] == status_codes.UNKNOWN_RESOURCE
    assert body["status_message"] == "Unknown resource"
    assert resp.status_code == 404
