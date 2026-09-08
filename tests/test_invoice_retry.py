"""Számlázás: átmeneti hiba retry + kimaradt számlák háttérpótlása."""
import sys
import types
from datetime import timedelta

import pytest
import requests

from tests.conftest import TestSession
from app.db.models import ChargePoint, ChargeSession, ChargingIntent
from app.ocpp.time_utils import utcnow
from app.services import invoice as invoice_mod
from app.services.invoice_retry import retry_missing_invoices_once


class _FakeHttpResponse:
    def __init__(self, status: int):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code} Server Error", response=self)


class _FakeResp:
    def __init__(self, status: int, invoice_number=None):
        self.response = _FakeHttpResponse(status)
        self.invoice_number = invoice_number


def _install_fake_szamlazz(monkeypatch, *, generate_results, query_results=None):
    """
    Hamis `szamlazz` modul. generate_results / query_results: sorban visszaadott
    _FakeResp-ek vagy kivételek (Exception példány → raise).
    """
    calls = {"generate": 0, "query": 0}
    gen_iter = iter(generate_results)
    q_iter = iter(query_results or [])

    def _next(it):
        r = next(it)
        if isinstance(r, BaseException):
            raise r
        return r

    class FakeClient:
        def __init__(self, agent_key):
            assert agent_key == "test-key"

        def generate_invoice(self, **kwargs):
            calls["generate"] += 1
            return _next(gen_iter)

        def query_invoice_xml(self, order_number="", invoice_number="", pdf=True):
            calls["query"] += 1
            return _next(q_iter)

    def _model(**kw):  # Header/Merchant/Buyer/Item helyettesítő
        return kw

    fake = types.ModuleType("szamlazz")
    fake.SzamlazzClient = FakeClient
    fake.Header = fake.Merchant = fake.Buyer = fake.Item = _model
    monkeypatch.setitem(sys.modules, "szamlazz", fake)
    monkeypatch.setenv("SZAMLAZZ_AGENT_KEY", "test-key")
    monkeypatch.setattr(invoice_mod, "_RETRY_DELAYS_S", (0.0, 0.0, 0.0))
    return calls


async def _create(**kw):
    return await invoice_mod.create_session_invoice(
        session_id=55, energy_kwh=8.573, captured_huf=1457.0, cp_ocpp_id="cp1",
        buyer_email="x@example.hu", **kw,
    )


async def test_transient_5xx_is_retried_then_succeeds(monkeypatch):
    calls = _install_fake_szamlazz(monkeypatch, generate_results=[
        _FakeResp(520), _FakeResp(502), _FakeResp(200, "E-EV-2026-9"),
    ])
    assert await _create() == "E-EV-2026-9"
    assert calls["generate"] == 3


async def test_connection_error_is_retried(monkeypatch):
    calls = _install_fake_szamlazz(monkeypatch, generate_results=[
        requests.exceptions.ConnectionError("boom"), _FakeResp(200, "E-1"),
    ])
    assert await _create() == "E-1"
    assert calls["generate"] == 2


async def test_gives_up_after_all_retries(monkeypatch):
    calls = _install_fake_szamlazz(monkeypatch, generate_results=[_FakeResp(520)] * 4)
    assert await _create() is None
    assert calls["generate"] == 4  # 1 + 3 retry


async def test_non_transient_error_not_retried(monkeypatch):
    calls = _install_fake_szamlazz(monkeypatch, generate_results=[_FakeResp(400), _FakeResp(200, "E-X")])
    assert await _create() is None
    assert calls["generate"] == 1


async def _seed_session(*, finished_ago=timedelta(minutes=30), intent_status="paid", invoice_number=None):
    async with TestSession() as s:
        cp = ChargePoint(ocpp_id="CPINV", connector_type="Type2", max_power_kw=11.0,
                         status="available", last_seen_at=utcnow(), is_published=True)
        s.add(cp)
        await s.flush()
        intent = ChargingIntent(
            charge_point_id=cp.id, connector_id=1, anonymous_email="ugyfel@example.hu",
            status=intent_status, hold_amount_huf=5000, expires_at=utcnow(),
            stripe_payment_intent_id="pi_test", billing_name="Teszt Elek",
        )
        s.add(intent)
        await s.flush()
        cs = ChargeSession(
            charge_point_id=cp.id, connector_id=1, ocpp_transaction_id="77",
            started_at=utcnow() - finished_ago - timedelta(hours=1),
            finished_at=utcnow() - finished_ago,
            energy_kwh=8.573, cost_huf=1457.41, anonymous_email="ugyfel@example.hu",
            intent_id=intent.id, invoice_number=invoice_number,
        )
        s.add(cs)
        await s.commit()
        return cs.id


async def _invoice_number(session_id: int):
    async with TestSession() as s:
        return (await s.get(ChargeSession, session_id)).invoice_number


async def test_background_retry_issues_missing_invoice(monkeypatch):
    sid = await _seed_session()
    calls = _install_fake_szamlazz(
        monkeypatch,
        query_results=[_FakeResp(200, None)],          # nincs még a Számlázz.hu-n
        generate_results=[_FakeResp(200, "E-EV-2026-10")],
    )
    assert await retry_missing_invoices_once() == 1
    assert calls == {"generate": 1, "query": 1}
    assert await _invoice_number(sid) == "E-EV-2026-10"


async def test_background_retry_reuses_existing_invoice_no_duplicate(monkeypatch):
    sid = await _seed_session()
    calls = _install_fake_szamlazz(
        monkeypatch,
        query_results=[_FakeResp(200, "E-EV-2026-3")],  # már kiállt, csak a válasz veszett el
        generate_results=[_FakeResp(200, "SHOULD-NOT-HAPPEN")],
    )
    assert await retry_missing_invoices_once() == 1
    assert calls["generate"] == 0
    assert await _invoice_number(sid) == "E-EV-2026-3"


async def test_background_retry_skips_fresh_unpaid_and_invoiced(monkeypatch):
    await _seed_session(finished_ago=timedelta(minutes=1))          # túl friss
    calls = _install_fake_szamlazz(monkeypatch, generate_results=[], query_results=[])
    assert await retry_missing_invoices_once() == 0
    assert calls == {"generate": 0, "query": 0}

    async with TestSession() as s:
        for cs in (await s.execute(__import__("sqlalchemy").select(ChargeSession))).scalars():
            cs.finished_at = utcnow() - timedelta(minutes=30)
            cs.invoice_number = "E-DONE"
        await s.commit()
    assert await retry_missing_invoices_once() == 0

    async with TestSession() as s:
        for cs in (await s.execute(__import__("sqlalchemy").select(ChargeSession))).scalars():
            cs.invoice_number = None
        for it in (await s.execute(__import__("sqlalchemy").select(ChargingIntent))).scalars():
            it.status = "expired"
        await s.commit()
    assert await retry_missing_invoices_once() == 0
    assert calls == {"generate": 0, "query": 0}
