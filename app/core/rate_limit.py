# app/core/rate_limit.py
"""Egyszerű, folyamaton belüli rate limit a publikus végpontokra (ASGI middleware).

Egy backend-példány fut (uvicorn, 1 worker), így a memóriabeli csúszóablak elég; újraindításkor
nullázódik, ami itt nem baj. Kulcs: (szabály, kliens-IP).

Kliens-IP: élesben a Cloudflare tunnel az egyetlen bejárat (a backend portja csak a szerver
localhostján van kint), és a Cloudflare a CF-Connecting-IP fejlécet mindig felülírja a valódi
kliens-IP-vel – ez tehát megbízható. Az X-Forwarded-For-t NEM használjuk: abban a kliens által
küldött hamis értékek is ott lehetnek (és az uvicorn --forwarded-allow-ips '*' mellett a
request.client is ebből jön). Ha a backend valaha nem Cloudflare mögött fut, a
RATE_LIMIT_TRUST_CF_HEADER=0 kikapcsolja a fejléc használatát (akkor a TCP-peer címe a kulcs).

Env: RATE_LIMIT_ENABLED (alap: 1).
"""
from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple


@dataclass(frozen=True)
class Rule:
    name: str
    method: str
    pattern: re.Pattern
    limit: int
    window_s: int


# Bőkezű korlátok: a frontend 5 mp-enként frissíti a töltőlistát és 3 mp-enként pollozza a
# töltést; mobilhálózaton (CGNAT) sok ügyfél osztozhat egy IP-n.
RULES: Tuple[Rule, ...] = (
    Rule("charge_points", "GET", re.compile(r"^/api/charge-points(/[^/]*)?/?$"), 240, 60),
    Rule("intent_create", "POST", re.compile(r"^/api/intents/?$"), 20, 600),
    Rule("session_view", "GET", re.compile(r"^/api/sessions/(by-intent/)?\d+/?$"), 240, 60),
    Rule("session_stop", "POST", re.compile(r"^/api/sessions/\d+/stop/?$"), 20, 60),
    Rule("auth", "*", re.compile(r"^/api/auth/"), 60, 60),
)


def _enabled() -> bool:
    return (os.environ.get("RATE_LIMIT_ENABLED") or "1").strip().lower() not in ("0", "false", "no")


def _trust_cf() -> bool:
    return (os.environ.get("RATE_LIMIT_TRUST_CF_HEADER") or "1").strip().lower() not in ("0", "false", "no")


def client_ip(scope) -> str:
    if _trust_cf():
        for k, v in scope.get("headers") or []:
            if k == b"cf-connecting-ip":
                ip = v.decode("latin-1").strip()
                if ip:
                    return ip
    client = scope.get("client")
    return client[0] if client else "unknown"


class _Store:
    def __init__(self) -> None:
        self.hits: Dict[Tuple[str, str], Deque[float]] = {}
        self._last_gc = time.monotonic()

    def hit(self, rule: Rule, ip: str, now: float) -> Optional[int]:
        """None = mehet; különben a javasolt Retry-After másodperc."""
        key = (rule.name, ip)
        q = self.hits.get(key)
        if q is None:
            q = self.hits[key] = deque()
        cutoff = now - rule.window_s
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= rule.limit:
            return max(1, int(q[0] + rule.window_s - now) + 1)
        q.append(now)
        self._gc(now)
        return None

    def _gc(self, now: float) -> None:
        if now - self._last_gc < 300:
            return
        self._last_gc = now
        max_window = max(r.window_s for r in RULES)
        for key in [k for k, q in self.hits.items() if not q or q[-1] <= now - max_window]:
            self.hits.pop(key, None)

    def clear(self) -> None:
        self.hits.clear()


STORE = _Store()


def _match(method: str, path: str) -> Optional[Rule]:
    for r in RULES:
        if (r.method == "*" or r.method == method) and r.pattern.match(path):
            return r
    return None


class RateLimitMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not _enabled():
            return await self.app(scope, receive, send)
        method = scope.get("method", "GET")
        if method == "OPTIONS":
            return await self.app(scope, receive, send)
        rule = _match(method, scope.get("path", ""))
        if rule is None:
            return await self.app(scope, receive, send)
        retry = STORE.hit(rule, client_ip(scope), time.monotonic())
        if retry is None:
            return await self.app(scope, receive, send)
        body = json.dumps({"detail": {
            "error": "rate_limited",
            "hint": "Túl sok kérés érkezett. Kérjük, próbálja újra néhány perc múlva.",
        }}, ensure_ascii=False).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"retry-after", str(retry).encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
