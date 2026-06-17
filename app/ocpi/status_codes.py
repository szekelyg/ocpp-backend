"""OCPI 2.2.1 status codes (response body ``status_code``).

These are OCPI-protocol codes carried inside the JSON envelope, independent of
the HTTP status. See OCPI 2.2.1 §6 (Status codes).
"""
from __future__ import annotations

# 1xxx — Success
SUCCESS = 1000

# 2xxx — Client errors
CLIENT_ERROR = 2000
INVALID_PARAMETERS = 2001          # invalid or missing parameters
NOT_ENOUGH_INFORMATION = 2002
UNKNOWN_RESOURCE = 2003            # unknown location/EVSE/connector/token...

# 3xxx — Server errors
SERVER_ERROR = 3000
UNABLE_TO_USE_CLIENT_API = 3001    # could not reach/use the partner's API
UNSUPPORTED_VERSION = 3002
NO_MATCHING_ENDPOINTS = 3003       # no endpoints in common during registration

_MESSAGES = {
    SUCCESS: "Success",
    CLIENT_ERROR: "Client error",
    INVALID_PARAMETERS: "Invalid or missing parameters",
    NOT_ENOUGH_INFORMATION: "Not enough information",
    UNKNOWN_RESOURCE: "Unknown resource",
    SERVER_ERROR: "Server error",
    UNABLE_TO_USE_CLIENT_API: "Unable to use the client's API",
    UNSUPPORTED_VERSION: "Unsupported version",
    NO_MATCHING_ENDPOINTS: "No matching endpoints or expected endpoints missing",
}


def default_message(status_code: int) -> str:
    return _MESSAGES.get(status_code, "")
