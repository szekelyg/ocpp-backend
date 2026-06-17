"""Outbound OCPI HTTP client.

Used by the registration handshake (fetch a partner's versions/endpoints) and,
from phase F5, to push Locations/Sessions/CDRs/Tokens to partners. Tokens we
send are base64-encoded per OCPI 2.2.1.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger("ocpi")

_TIMEOUT = httpx.Timeout(15.0)


def auth_header(token: str) -> dict:
    """OCPI 2.2.1 outgoing auth header (base64-encoded token)."""
    encoded = base64.b64encode(token.encode("utf-8")).decode("ascii")
    return {"Authorization": f"Token {encoded}"}


def _correlation_headers() -> dict:
    # OCPI requires X-Request-ID; X-Correlation-ID is recommended. We don't have
    # a request-scoped id here, so generate trivial static-free values per call.
    return {"Accept": "application/json"}


class OCPIClientError(Exception):
    """Raised when a partner call fails at transport or OCPI-envelope level."""


async def get_json(url: str, token: str) -> Any:
    """GET an OCPI endpoint, validate the envelope, return its ``data``."""
    headers = {**auth_header(token), **_correlation_headers()}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, headers=headers)
    return _unwrap(url, resp)


async def post_json(url: str, token: str, payload: Any) -> Any:
    headers = {**auth_header(token), **_correlation_headers()}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)
    return _unwrap(url, resp)


async def put_json(url: str, token: str, payload: Any) -> Any:
    headers = {**auth_header(token), **_correlation_headers()}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.put(url, headers=headers, json=payload)
    return _unwrap(url, resp)


async def patch_json(url: str, token: str, payload: Any) -> Any:
    headers = {**auth_header(token), **_correlation_headers()}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.patch(url, headers=headers, json=payload)
    return _unwrap(url, resp)


def _unwrap(url: str, resp: httpx.Response) -> Any:
    if resp.status_code >= 400:
        raise OCPIClientError(f"{url} -> HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as e:
        raise OCPIClientError(f"{url} -> non-JSON response") from e
    status_code = body.get("status_code")
    if status_code is not None and int(status_code) >= 2000:
        raise OCPIClientError(f"{url} -> OCPI status {status_code}: {body.get('status_message')}")
    return body.get("data")


async def raw_post(url: str, token: Optional[str], payload: Any) -> int:
    """POST an OCPI object (e.g. a CommandResult callback) and return HTTP status.

    Used for fire-and-forget callbacks where we only care that it was delivered.
    """
    headers = _correlation_headers()
    if token:
        headers.update(auth_header(token))
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, headers=headers, json=payload)
        return resp.status_code
    except httpx.HTTPError as e:
        logger.warning(f"OCPI callback POST failed url={url}: {e}")
        return 0
