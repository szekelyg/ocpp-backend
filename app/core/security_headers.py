# app/core/security_headers.py
"""Biztonsági válaszfejlécek minden HTTP-válaszra (ASGI middleware).

A backend előtt nincs fejléceket adó proxy (Cloudflare tunnel → uvicorn), ezért itt adjuk.
A CSP egyelőre csak Report-Only: semmit nem tilt, a megsértéseket a böngésző konzolja mutatja –
élesre (Content-Security-Policy) akkor váltható, ha a felületen nem látszik megsértés.
"""
from __future__ import annotations

from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders

from app.services import keycloak

# A térkép csempéi (frontend/src/components/map/MapView.jsx)
_MAP_TILES = "https://*.tile.openstreetmap.org"


def _csp() -> str:
    connect = "'self'"
    issuer = keycloak.issuer()          # a SPA innen kér tokent (PKCE) – futásidőben olvasva
    if issuer:
        u = urlsplit(issuer)
        connect += f" {u.scheme}://{u.netloc}"
    return (
        "default-src 'self'; "
        f"connect-src {connect}; "
        f"img-src 'self' data: {_MAP_TILES}; "
        "frame-ancestors 'none'"
    )


class SecurityHeadersMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Content-Security-Policy-Report-Only", _csp())
            await send(message)

        await self.app(scope, receive, send_with_headers)
