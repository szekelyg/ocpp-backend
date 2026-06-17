"""OCPI Versions module schemas."""
from __future__ import annotations

from .common import OCPISchema


class Version(OCPISchema):
    version: str           # "2.2.1"
    url: str               # version details URL


class Endpoint(OCPISchema):
    identifier: str        # ModuleID, e.g. "locations"
    role: str              # InterfaceRole: SENDER / RECEIVER
    url: str


class VersionDetails(OCPISchema):
    version: str
    endpoints: list[Endpoint]
