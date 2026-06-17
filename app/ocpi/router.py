"""Top-level OCPI router.

Assembles every OCPI module router under the ``/ocpi`` prefix. Module routers are
added phase by phase; this file is the single mount point used by app/main.py.
"""
from __future__ import annotations

from fastapi import APIRouter

from .routers.versions import router as versions_router
from .routers.credentials import router as credentials_router
from .routers.locations import router as locations_router
from .routers.sessions import router as sessions_router
from .routers.cdrs import router as cdrs_router
from .routers.tariffs import router as tariffs_router
from .routers.tokens import router as tokens_router
from .routers.commands import router as commands_router

# prefix="/ocpi" — sibling of the internal "/api"; NOT under it.
router = APIRouter(prefix="/ocpi", tags=["ocpi"])

# Versions live at the unversioned root (GET /ocpi/versions, GET /ocpi/2.2.1).
router.include_router(versions_router)

# 2.2.1 module endpoints.
router.include_router(credentials_router)
router.include_router(locations_router)
router.include_router(sessions_router)
router.include_router(cdrs_router)
router.include_router(tariffs_router)
router.include_router(tokens_router)
router.include_router(commands_router)
