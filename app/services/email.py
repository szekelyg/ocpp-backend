# app/services/email.py
"""
Email küldés Resend API-on keresztül (https://resend.com).

Konfig .env-ben:
  RESEND_API_KEY=re_xxxxxxxxxxxx
  RESEND_FROM=service@energiafelho.hu     (opcionális, ez az alapértelmezett)
  PUBLIC_BASE_URL=https://energiafelho.hu (session link generáláshoz)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("email")

_RESEND_URL = "https://api.resend.com/emails"


async def _send(to: str, subject: str, html: str) -> bool:
    api_key = os.environ.get("RESEND_API_KEY")
    from_addr = os.environ.get("RESEND_FROM", "service@energiafelho.hu")

    if not api_key:
        logger.warning("RESEND_API_KEY nincs beállítva – email nem lett elküldve")
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _RESEND_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"from": from_addr, "to": [to], "subject": subject, "html": html},
            )
            resp.raise_for_status()
            logger.info("Email elküldve → %s | %s", to, subject)
            return True
    except Exception as e:
        logger.exception("Email küldési hiba: %s", e)
        return False


def _base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


# ---------------------------------------------------------------------------
# Email sablonok
# ---------------------------------------------------------------------------

def _wrap(title: str, body: str) -> str:
    """Alap HTML wrapper – egységes kinézet minden emailhez."""
    return f"""<!DOCTYPE html>
<html lang="hu">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:'Segoe UI',Arial,sans-serif;color:#e2e8f0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;padding:32px 16px;">
    <tr><td align="center">
      <table width="100%" style="max-width:520px;background:#1e293b;border-radius:16px;overflow:hidden;
                                  border:1px solid #334155;">
        <!-- Header -->
        <tr>
          <td style="background:#1d4ed8;padding:20px 28px;">
            <span style="font-size:22px;font-weight:700;color:#fff;letter-spacing:-0.5px;">
              ⚡ Energia Felhő
            </span>
          </td>
        </tr>
        <!-- Body -->
        <tr>
          <td style="padding:28px;">
            {body}
          </td>
        </tr>
        <!-- Footer -->
        <tr>
          <td style="padding:16px 28px;border-top:1px solid #334155;">
            <p style="margin:0;font-size:12px;color:#64748b;">
              Ez egy automatikus értesítés. Kérdés esetén írj a
              <a href="mailto:service@energiafelho.hu" style="color:#60a5fa;">service@energiafelho.hu</a>
              címre.
            </p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _btn(url: str, label: str) -> str:
    return (
        f'<a href="{url}" style="display:inline-block;margin-top:20px;padding:12px 24px;'
        f'background:#1d4ed8;color:#fff;text-decoration:none;border-radius:10px;'
        f'font-weight:600;font-size:14px;">{label}</a>'
    )


def _stat(label: str, value: str) -> str:
    return (
        f'<tr>'
        f'<td style="padding:8px 0;color:#94a3b8;font-size:14px;width:120px;">{label}</td>'
        f'<td style="padding:8px 0;color:#f1f5f9;font-size:14px;font-weight:600;">{value}</td>'
        f'</tr>'
    )


# ---------------------------------------------------------------------------
# Publikus küldő függvények
# ---------------------------------------------------------------------------

async def send_stop_code_email(
    to: str,
    stop_code: str,
    session_id: int,
    cp_ocpp_id: str = "—",
) -> bool:
    """Töltés indult – stop kód + link."""
    session_url = f"{_base_url()}/charging/{session_id}"

    body = f"""
    <h2 style="margin:0 0 8px;font-size:20px;color:#f1f5f9;">Töltés elindult</h2>
    <p style="margin:0 0 20px;color:#94a3b8;font-size:14px;">
      A töltő (<strong style="color:#e2e8f0;">{cp_ocpp_id}</strong>) fogadta a kérést.
      Ha az autó már be van dugva, a töltés azonnal indul – egyébként csatlakoztassa most.
    </p>

    <div style="background:#0f172a;border:1px solid #334155;border-radius:12px;padding:20px 24px;
                text-align:center;margin-bottom:20px;">
      <p style="margin:0 0 6px;font-size:12px;color:#64748b;text-transform:uppercase;
                letter-spacing:1px;">Stop kód</p>
      <span style="font-family:monospace;font-size:36px;font-weight:700;
                   letter-spacing:8px;color:#60a5fa;">{stop_code}</span>
      <p style="margin:8px 0 0;font-size:12px;color:#64748b;">
        Ezt a kódot tárold el – ezzel tudod leállítani a töltést.
      </p>
    </div>

    <table cellpadding="0" cellspacing="0" style="width:100%;">
      {_stat("Töltő azonosító", cp_ocpp_id)}
      {_stat("Session ID", str(session_id))}
    </table>

    {_btn(session_url, "Töltés státusz megtekintése →")}

    <p style="margin:20px 0 0;font-size:12px;color:#64748b;">
      Ha nem Ön indította ezt a töltést, kérjük haladéktalanul vegye fel velünk a kapcsolatot.
    </p>
    """

    return await _send(
        to=to,
        subject=f"⚡ Stop kód: {stop_code} – Energia Felhő töltés",
        html=_wrap("Töltés elindult", body),
    )


async def send_no_start_email(
    to: str,
    session_id: int,
    cp_ocpp_id: str = "—",
) -> bool:
    """Töltés nem indult el (autó nem csatlakozott időben) – értesítés + visszatérítés."""
    body = f"""
    <h2 style="margin:0 0 8px;font-size:20px;color:#f1f5f9;">Töltés nem indult el</h2>
    <p style="margin:0 0 20px;color:#94a3b8;font-size:14px;">
      A töltő (<strong style="color:#e2e8f0;">{cp_ocpp_id}</strong>) 15 percen belül
      nem kapott csatlakozást. A munkamenet automatikusan lezárult.
    </p>

    <div style="background:#0f172a;border:1px solid #92400e;border-radius:12px;padding:16px 24px;
                margin-bottom:20px;">
      <p style="margin:0;font-size:14px;color:#fbbf24;font-weight:600;">
        💳 A befizetett összeg visszatérítése folyamatban van.
      </p>
      <p style="margin:8px 0 0;font-size:12px;color:#94a3b8;">
        A visszautalás általában 1–5 munkanapot vesz igénybe, a bankjától függően.
        Ha ezután sem látja a jóváírást, kérjük vegye fel velünk a kapcsolatot.
      </p>
    </div>

    <table cellpadding="0" cellspacing="0" style="width:100%;">
      {_stat("Töltő azonosító", cp_ocpp_id)}
      {_stat("Session ID", str(session_id))}
    </table>
    """

    return await _send(
        to=to,
        subject="⚠️ Töltés nem indult el – visszatérítés folyamatban",
        html=_wrap("Töltés nem indult el", body),
    )


async def send_receipt_email(
    to: str,
    session_id: int,
    cp_ocpp_id: str = "—",
    duration_s: Optional[int] = None,
    energy_kwh: Optional[float] = None,
    cost_huf: Optional[float] = None,
) -> bool:
    """Töltés befejezve – bizonylat."""

    def fmt_duration(s: Optional[int]) -> str:
        if not s:
            return "—"
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h}ó {m}p {sec}mp"
        if m:
            return f"{m}p {sec}mp"
        return f"{sec}mp"

    energy_str = f"{energy_kwh:.3f} kWh" if energy_kwh is not None else "—"
    cost_str = f"{int(round(cost_huf)):,} Ft".replace(",", "\u202f") if cost_huf is not None else "—"

    body = f"""
    <h2 style="margin:0 0 8px;font-size:20px;color:#f1f5f9;">Töltés befejezve</h2>
    <p style="margin:0 0 20px;color:#94a3b8;font-size:14px;">
      Köszönjük, hogy az Energia Felhő hálózatát választotta!
    </p>

    <table cellpadding="0" cellspacing="0"
           style="width:100%;background:#0f172a;border:1px solid #334155;
                  border-radius:12px;padding:4px 16px;">
      <tbody>
        {_stat("Töltő", cp_ocpp_id)}
        {_stat("Session ID", str(session_id))}
        {_stat("Időtartam", fmt_duration(duration_s))}
        {_stat("Energia", energy_str)}
        {_stat("Összeg", cost_str)}
      </tbody>
    </table>

    <p style="margin:20px 0 0;font-size:12px;color:#64748b;">
      A tényleges elszámolás az OCPP mérési adatok alapján történik.
      Vitás esetben kérjük vegye fel velünk a kapcsolatot.
    </p>
    """

    return await _send(
        to=to,
        subject="✓ Töltési bizonylat – Energia Felhő",
        html=_wrap("Töltési bizonylat", body),
    )
