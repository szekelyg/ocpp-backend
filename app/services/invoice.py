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

import logging
import math
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("invoice")

# 27% ÁFA – Magyarország
_VAT_RATE = 27
_VAT_DIVISOR = 1 + _VAT_RATE / 100  # 1.27


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _gross_to_net_vat(gross: float) -> tuple[float, float]:
    """Bruttó összegből nettó + ÁFA kiszámítása (27%)."""
    net = round(gross / _VAT_DIVISOR, 2)
    vat = round(gross - net, 2)
    return net, vat


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
            email_text="Mellékeljük a töltési session számlájét. Köszönjük, hogy az Energiafelhő hálózatát választotta!",
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

        # Tétel: töltési szolgáltatás kWh-ban vagy egységáron
        if energy_kwh and energy_kwh > 0:
            quantity = round(energy_kwh, 3)
            unit = "kWh"
            net_unit = round(captured_huf / _VAT_DIVISOR / quantity, 2)
        else:
            quantity = 1.0
            unit = "db"
            net_unit = round(captured_huf / _VAT_DIVISOR, 2)

        net_total = round(net_unit * quantity, 2)
        vat_amount = round(captured_huf - net_total, 2)
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

        response = client.generate_invoice(
            header=header,
            merchant=merchant,
            buyer=buyer,
            items=[item],
            e_invoice=True,
            invoice_download=False,
        )
        response.response.raise_for_status()

        invoice_number = response.invoice_number
        logger.info(f"Számla kiállítva: {invoice_number} session_id={session_id} bruttó={captured_huf} HUF")
        return invoice_number

    except Exception as e:
        logger.exception(f"Számla kiállítás sikertelen: session_id={session_id} err={e}")
        return None
