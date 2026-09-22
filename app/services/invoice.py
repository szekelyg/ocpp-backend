# app/services/invoice.py
"""
Számlázz.hu e-számla kiállítás a töltési session lezárásakor.

Konfig /etc/ocpp-backend.env-ben:
  SZAMLAZZ_AGENT_KEY=xxxxxxxxxxxxxxxx   (kisbetűs!)
  SZAMLAZZ_INVOICE_PREFIX=EV           (számla előtag, pl. EV-2026-0001)
  SZAMLAZZ_BANK_NAME=OTP Bank
  SZAMLAZZ_BANK_ACCOUNT=11111111-22222222-33333333
  SZAMLAZZ_REPLY_EMAIL=szerviz@energiafelho.hu
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("invoice")

# Átmeneti hibánál (Számlázz.hu 5xx, hálózati hiba, timeout) ennyiszer próbálkozunk
# újra, egyre hosszabb várakozással. A nem átmeneti hibák (pl. hibás vevőadat,
# rossz agent kulcs) azonnal feladják. Ha ez sem sikerül, a háttérfolyamat
# (app.services.invoice_retry) később pótolja a számlát.
_RETRY_DELAYS_S = (5.0, 20.0, 60.0)

# 27% ÁFA – Magyarország
_VAT_RATE = 27
_VAT_DIVISOR = 1 + _VAT_RATE / 100  # 1.27


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


class TransientInvoiceError(Exception):
    """Átmeneti hiba: érdemes később újrapróbálni (Számlázz.hu 5xx, hálózat, timeout)."""


def _is_transient(exc: BaseException) -> bool:
    try:
        import requests  # type: ignore
    except ImportError:  # pragma: no cover
        return False
    if isinstance(exc, requests.exceptions.HTTPError):
        resp = getattr(exc, "response", None)
        code = getattr(resp, "status_code", None)
        return code is not None and code >= 500
    return isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))


async def find_invoice_number_by_order(session_id: int) -> Optional[str]:
    """
    Megnézi a Számlázz.hu-n, hogy ehhez a sessionhöz (rendelésszám) van-e már számla.
    Ezzel kerüljük el a dupla számlát, ha a kiállítás sikerült, de a válasz elveszett.
    Visszaadja a számlaszámot vagy None-t (nincs számla / nem sikerült lekérdezni).
    """
    agent_key = _env("SZAMLAZZ_AGENT_KEY")
    if not agent_key:
        return None
    try:
        from szamlazz import SzamlazzClient  # type: ignore
    except ImportError:
        return None

    def _do() -> Optional[str]:
        client = SzamlazzClient(agent_key=agent_key)
        resp = client.query_invoice_xml(order_number=str(session_id), pdf=False)
        resp.response.raise_for_status()
        return resp.invoice_number or None

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        logger.warning(f"Számla lekérdezés sikertelen: session_id={session_id} err={e}")
        return None


async def fetch_invoice_pdf(invoice_number: str) -> Optional[bytes]:
    """
    A kiállított e-számla PDF-je a Számlázz.hu-ról (GET /api/me/sessions/{id}/invoice).
    A PDF-et nem tároljuk; minden letöltés a Számlázz.hu Agent API-t kérdezi.
    None, ha nincs agent kulcs / lib, vagy a lekérés nem sikerült.
    """
    agent_key = _env("SZAMLAZZ_AGENT_KEY")
    if not agent_key or not invoice_number:
        return None
    try:
        from szamlazz import SzamlazzClient  # type: ignore
    except ImportError:
        return None

    def _do() -> Optional[bytes]:
        client = SzamlazzClient(agent_key=agent_key)
        resp = client.query_invoice_pdf(invoice_number=invoice_number)
        if resp.has_errors:
            logger.warning(f"Számla PDF lekérés hiba: {invoice_number} {resp.error_code} {resp.error_message}")
            return None
        data = resp.get_pdf_bytes()
        return data if data and data[:4] == b"%PDF" else None

    try:
        return await asyncio.to_thread(_do)
    except Exception as e:
        logger.warning(f"Számla PDF lekérés sikertelen: {invoice_number} err={e}")
        return None


async def create_session_invoice(
    session_id: int,
    energy_kwh: Optional[float],
    captured_huf: float,
    cp_ocpp_id: str,
    buyer_email: str,
    buyer_name: Optional[str] = None,
    buyer_zip: Optional[str] = None,
    buyer_city: Optional[str] = None,
    buyer_street: Optional[str] = None,
    buyer_country: Optional[str] = None,
    buyer_tax_number: Optional[str] = None,
    buyer_company: Optional[str] = None,
    billing_type: Optional[str] = None,
) -> Optional[str]:
    """
    Számla kiállítása a töltési session után.
    Visszaadja a számlaszámot, vagy None-t hiba esetén.
    captured_huf: a Stripe-on ténylegesen levont bruttó összeg (HUF)
    """
    agent_key = _env("SZAMLAZZ_AGENT_KEY")
    if not agent_key:
        logger.warning("SZAMLAZZ_AGENT_KEY nincs beállítva – számla kihagyva")
        return None

    try:
        from szamlazz import SzamlazzClient, Header, Merchant, Buyer, Item  # type: ignore
    except ImportError:
        logger.error("szamlazz.py lib nincs telepítve – számla kihagyva")
        return None

    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        client = SzamlazzClient(agent_key=agent_key)

        header = Header(
            creating_date=today,
            payment_date=today,
            due_date=today,
            payment_type="Bankkártya",
            currency="HUF",
            invoice_language="hu",
            invoice_prefix=_env("SZAMLAZZ_INVOICE_PREFIX", "EV"),
            order_number=str(session_id),
        )

        merchant = Merchant(
            bank_name=_env("SZAMLAZZ_BANK_NAME", ""),
            bank_account_number=_env("SZAMLAZZ_BANK_ACCOUNT", ""),
            reply_email_address=_env("SZAMLAZZ_REPLY_EMAIL", "szerviz@energiafelho.hu"),
            email_subject=f"Számla – EV töltés (session #{session_id})",
            email_text="Mellékeljük a töltési session számlájét. Köszönjük, hogy az Energiafelhő Kft. hálózatát választotta!",
        )

        # Vevő neve: cégnév ha céges, egyébként teljes név
        name = buyer_company if (billing_type == "business" and buyer_company) else (buyer_name or buyer_email)
        # Cím összerakása
        address_parts = " ".join(filter(None, [buyer_street]))
        city = buyer_city or ""
        zip_code = buyer_zip or ""

        buyer = Buyer(
            name=name,
            zip_code=zip_code,
            city=city,
            address=address_parts or "-",
            email=buyer_email,
            tax_number=buyer_tax_number or "",
            tax_subject=-1,  # -1 = nem ismert / magánszemély
            send_email=True,
        )

        # Tétel: töltési szolgáltatás kWh-ban vagy egységáron.
        # A captured_huf egész HUF összeg (= Stripe capture). A nettó/ÁFA/bruttó
        # belsőleg konzisztens: vat = net * 27%, gross = net + vat. (A számlázz.hu
        # az ÁFA-t a kulcs alapján validálja, ezért NEM a captured-ből vonjuk ki.)
        gross_huf = float(round(captured_huf))
        if energy_kwh and energy_kwh > 0:
            quantity = round(energy_kwh, 3)
            unit = "kWh"
        else:
            quantity = 1.0
            unit = "db"

        net_unit = round(gross_huf / _VAT_DIVISOR / quantity, 2)
        net_total = round(net_unit * quantity, 2)
        vat_amount = round(net_total * _VAT_RATE / 100, 2)
        gross_total = round(net_total + vat_amount, 2)

        item = Item(
            name=f"Elektromos töltési szolgáltatás – {cp_ocpp_id}",
            quantity=str(quantity),
            quantity_unit=unit,
            unit_price=str(net_unit),
            vat_rate=str(_VAT_RATE),
            net_price=str(net_total),
            vat_amount=str(vat_amount),
            gross_amount=str(gross_total),
            comment_for_item=f"Session ID: {session_id}",
        )

        def _generate() -> Optional[str]:
            response = client.generate_invoice(
                header=header,
                merchant=merchant,
                buyer=buyer,
                items=[item],
                e_invoice=True,
                invoice_download=False,
            )
            response.response.raise_for_status()
            return response.invoice_number

        invoice_number = await _with_retries(_generate, session_id=session_id)
        if not invoice_number:
            logger.error(f"Számla kiállítás: nincs számlaszám a válaszban session_id={session_id}")
            return None
        logger.info(f"Számla kiállítva: {invoice_number} session_id={session_id} bruttó={captured_huf} HUF")
        return invoice_number

    except Exception as e:
        logger.exception(f"Számla kiállítás sikertelen: session_id={session_id} err={e}")
        return None


async def _with_retries(fn, *, session_id: int):
    """
    A blokkoló Számlázz.hu hívást szálban futtatja (nem fogja meg az event loopot),
    átmeneti hibánál a _RETRY_DELAYS_S szerint újrapróbálja.
    """
    attempts = len(_RETRY_DELAYS_S) + 1
    for i in range(attempts):
        try:
            return await asyncio.to_thread(fn)
        except Exception as e:
            if not _is_transient(e) or i == attempts - 1:
                raise
            delay = _RETRY_DELAYS_S[i]
            logger.warning(
                f"Számlázz.hu átmeneti hiba ({i + 1}/{attempts}), újra {delay:.0f}s után: "
                f"session_id={session_id} err={e}"
            )
            await asyncio.sleep(delay)
