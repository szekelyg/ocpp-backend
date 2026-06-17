"""OCPI configuration accessor.

Thin wrapper over the shared pydantic ``Settings`` (app/core/config.py) plus a
few derived helpers. Keeps all OCPI identity/handshake config in one place so
routers/services don't reach into ``settings`` or ``os.environ`` directly.
"""
from __future__ import annotations

import os
from functools import lru_cache

from app.core.config import settings

from . import OCPI_VERSION


def ocpi_enabled() -> bool:
    """OCPI is only served when explicitly enabled AND a Token A is configured.

    Mirrors the admin fail-closed posture: half-configured = disabled (the auth
    layer returns 503), never silently open.
    """
    return bool(settings.ocpi_enabled and settings.ocpi_token_a)


def country_code() -> str:
    return (settings.ocpi_country_code or "HU").upper()


def party_id() -> str:
    return (settings.ocpi_party_id or "ENF").upper()


def time_zone() -> str:
    return settings.ocpi_time_zone or "Europe/Budapest"


def evse_id_separator() -> str:
    return settings.ocpi_evse_id_separator or "*"


def default_city() -> str:
    return settings.ocpi_default_city or "N/A"


def country_alpha3() -> str:
    """ISO 3166-1 alpha-3 for the Location.country field (alpha-2 -> alpha-3)."""
    return _ALPHA2_TO_ALPHA3.get(country_code(), "HUN")


def default_tariff_id() -> str:
    """Stable id of the single env-derived tariff (referenced by Connectors/CDRs)."""
    return f"{party_id().lower()}-default"


# Minimal alpha-2 -> alpha-3 map (extend as more countries are operated).
_ALPHA2_TO_ALPHA3 = {
    "HU": "HUN", "AT": "AUT", "SK": "SVK", "RO": "ROU", "HR": "HRV",
    "SI": "SVN", "RS": "SRB", "DE": "DEU", "CZ": "CZE", "PL": "POL",
}


@lru_cache(maxsize=1)
def base_url() -> str:
    """External base URL (no trailing slash), e.g. ``https://ev.energiafelho.hu``.

    Falls back to the existing ``PUBLIC_BASE_URL`` env used by the Stripe flow.
    """
    url = settings.ocpi_base_url or os.environ.get("PUBLIC_BASE_URL") or ""
    return url.rstrip("/")


def versions_url() -> str:
    return f"{base_url()}/ocpi/versions"


def version_details_url() -> str:
    return f"{base_url()}/ocpi/{OCPI_VERSION}"


def module_url(identifier: str) -> str:
    """Absolute URL for a 2.2.1 module endpoint, e.g. ``.../ocpi/2.2.1/locations``."""
    return f"{base_url()}/ocpi/{OCPI_VERSION}/{identifier}"


def business_details() -> dict:
    """OCPI BusinessDetails for our CPO role object."""
    out: dict = {"name": settings.ocpi_business_name or "Energiafelhő"}
    if settings.ocpi_business_website:
        out["website"] = settings.ocpi_business_website
    if settings.ocpi_business_logo_url:
        out["logo"] = {
            "url": settings.ocpi_business_logo_url,
            "category": "OPERATOR",
            "type": "png",
        }
    return out
