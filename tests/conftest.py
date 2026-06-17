"""Shared pytest fixtures for the OCPI test-suite.

OCPI env + a test DATABASE_URL must be set *before* app.core.config.settings is
instantiated (module import time), so we set them at the very top.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("OCPI_ENABLED", "true")
os.environ.setdefault("OCPI_TOKEN_A", "test-token-a")
os.environ.setdefault("OCPI_BASE_URL", "https://cpo.test")
os.environ.setdefault("OCPI_COUNTRY_CODE", "HU")
os.environ.setdefault("OCPI_PARTY_ID", "ENF")
os.environ.setdefault("OCPI_BUSINESS_NAME", "Energiafelhő")
os.environ.setdefault("OCPP_PRICE_HUF_PER_KWH", "170")
os.environ.setdefault("STRIPE_MIN_HUF", "500")

import base64
import pathlib
import tempfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db.base import Base
import app.db.models  # noqa: F401  (register all ORM tables on Base.metadata)
from app.api.deps import get_db
from app.main import app

# File-based SQLite + NullPool: connections are never reused across pytest-asyncio
# function-scoped event loops (which would raise "Event loop is closed"), and the
# schema persists across the separate connections within a test. Per-test
# create_all/drop_all gives isolation.
_DB_PATH = pathlib.Path(tempfile.gettempdir()) / "ocpi_test.db"
_DB_PATH.unlink(missing_ok=True)
_test_engine = create_async_engine(
    f"sqlite+aiosqlite:///{_DB_PATH}",
    poolclass=NullPool,
)
TestSession = async_sessionmaker(_test_engine, expire_on_commit=False, class_=AsyncSession)

# Background tasks (CDR snapshot, command result finalize) open their own session
# via app.db.session.AsyncSessionLocal. Point it at the test engine so they use
# the same (loop-safe, NullPool) DB instead of the production in-memory engine.
import app.db.session as _db_session_module
_db_session_module.AsyncSessionLocal = TestSession


def token_header(token: str) -> dict:
    """OCPI Authorization header with a base64-encoded token."""
    encoded = base64.b64encode(token.encode()).decode()
    return {"Authorization": f"Token {encoded}"}


@pytest_asyncio.fixture(autouse=True)
async def _create_schema():
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def _get_test_db():
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def db():
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def client():
    app.dependency_overrides[get_db] = _get_test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


PARTY_TOKEN_C = "emsp-token-c"


@pytest_asyncio.fixture
async def party_token():
    """Insert a pre-registered eMSP party and return its Token C (for module tests)."""
    from app.db.models import OcpiParty
    async with TestSession() as s:
        s.add(OcpiParty(
            role="EMSP", country_code="HU", party_id="EMS",
            business_name="Test eMSP",
            token_incoming=PARTY_TOKEN_C, token_outgoing="token-b",
            status="REGISTERED",
        ))
        await s.commit()
    return PARTY_TOKEN_C
