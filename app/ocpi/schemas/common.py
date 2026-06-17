"""Shared OCPI 2.2.1 schema building blocks.

``OCPISchema`` is the base for every OCPI object: it ignores unknown fields on
input (partners send richer objects than we model) and serializes datetimes in
OCPI format via the ``OCPIDateTime`` annotated type.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, PlainSerializer

from ..envelope import format_ocpi_datetime

# datetime that serializes to OCPI's RFC-3339 "...Z" form in JSON mode.
OCPIDateTime = Annotated[
    datetime,
    PlainSerializer(format_ocpi_datetime, return_type=str, when_used="json"),
]


class OCPISchema(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class DisplayText(OCPISchema):
    language: str          # ISO 639-1, e.g. "hu"
    text: str              # max 512


class GeoLocation(OCPISchema):
    latitude: str          # decimal degrees as string, max 7 decimals
    longitude: str


class AdditionalGeoLocation(OCPISchema):
    latitude: str
    longitude: str
    name: Optional[DisplayText] = None


class Image(OCPISchema):
    url: str
    thumbnail: Optional[str] = None
    category: str          # CHARGER / ENTRANCE / LOCATION / NETWORK / OPERATOR / OWNER / OTHER
    type: str              # file type, e.g. "png"
    width: Optional[int] = None
    height: Optional[int] = None


class BusinessDetails(OCPISchema):
    name: str
    website: Optional[str] = None
    logo: Optional[Image] = None


class Price(OCPISchema):
    """OCPI Price: amounts excluding and (optionally) including VAT."""
    excl_vat: float
    incl_vat: Optional[float] = None
