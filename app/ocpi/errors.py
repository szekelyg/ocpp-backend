"""OCPI exception type + handlers so every error renders inside the envelope.

FastAPI's default error body is ``{"detail": ...}``; OCPI partners expect the
standard ``{status_code, status_message, timestamp}`` envelope. Raising
:class:`OCPIException` anywhere in OCPI code routes through the handler below.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request

from . import envelope, status_codes

logger = logging.getLogger("ocpi")


class OCPIException(Exception):
    def __init__(
        self,
        status_code: int,
        status_message: str | None = None,
        *,
        http_status: int = 200,
        headers: dict | None = None,
    ):
        self.status_code = status_code
        self.status_message = status_message or status_codes.default_message(status_code)
        self.http_status = http_status
        self.headers = headers
        super().__init__(self.status_message)


def add_ocpi_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(OCPIException)
    async def _handle_ocpi_exception(_request: Request, exc: OCPIException):
        return envelope.error(
            exc.status_code,
            exc.status_message,
            http_status=exc.http_status,
            headers=exc.headers,
        )
