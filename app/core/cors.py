# app/core/cors.py
"""
Útvonalra szűkített CORS: a Starlette CORSMiddleware-t csak a megadott prefix alatt
(/api/me/*) futtatjuk, hogy a portál (my.energiafelho.hu) böngészőből hívhassa a saját
töltés-listát Bearer tokennel. Minden más útvonal CORS nélkül marad (mint eddig).

Env: PORTAL_ORIGINS – vesszővel elválasztott originek, alap: https://my.energiafelho.hu
"""
from __future__ import annotations

import os

from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

DEFAULT_PORTAL_ORIGINS = ("https://my.energiafelho.hu",)


def portal_origins() -> list[str]:
    raw = os.environ.get("PORTAL_ORIGINS")
    if raw is None:
        return list(DEFAULT_PORTAL_ORIGINS)
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]


class PathScopedCORS:
    def __init__(self, app: ASGIApp, path_prefix: str, **cors_kwargs) -> None:
        self.app = app
        self.path_prefix = path_prefix
        self.cors = CORSMiddleware(app, **cors_kwargs)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path", "").startswith(self.path_prefix):
            await self.cors(scope, receive, send)
            return
        await self.app(scope, receive, send)
