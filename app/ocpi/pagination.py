"""OCPI pagination helpers.

OCPI list endpoints page with ``offset`` + ``limit`` query params and return
``X-Total-Count``, ``X-Limit`` and a ``Link`` header pointing at the next page
(``<url>; rel="next"``). See OCPI 2.2.1 §4.2 (Pagination).
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qs

from fastapi import Request

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


@dataclass
class Page:
    offset: int
    limit: int


def parse_page(offset: int | None, limit: int | None) -> Page:
    """Clamp client-supplied offset/limit to safe bounds."""
    o = max(0, int(offset or 0))
    raw = DEFAULT_LIMIT if limit is None else int(limit)
    lim = max(1, min(raw, MAX_LIMIT))
    return Page(offset=o, limit=lim)


def _with_query(url: str, **params) -> str:
    parts = urlsplit(url)
    q = parse_qs(parts.query)
    for k, v in params.items():
        q[k] = [str(v)]
    new_query = urlencode({k: v[0] for k, v in q.items()})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def pagination_headers(request: Request, page: Page, total: int) -> dict:
    """Build the OCPI pagination response headers.

    ``Link`` (rel="next") is only emitted when a further page exists.
    """
    headers = {
        "X-Total-Count": str(total),
        "X-Limit": str(page.limit),
    }
    next_offset = page.offset + page.limit
    if next_offset < total:
        next_url = _with_query(str(request.url), offset=next_offset, limit=page.limit)
        headers["Link"] = f'<{next_url}>; rel="next"'
    return headers
