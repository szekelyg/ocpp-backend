# app/api/routers/me.py
"""
A bejelentkezett fiók saját adatai – Keycloak access tokennel (vagy egy még le nem járt
régi v1 e-mail-tokennel; app.api.deps.get_current_identity). Ezt hívja az ev SPA "Töltéseim" oldala és a portál
(my.energiafelho.hu) is; a szerződést a docs/KEYCLOAK.md rögzíti.

  GET /api/me                        → profil (e-mail, név, mentett számlázási adatok, keycloak_linked)
  GET /api/me/sessions?limit&offset  → { sessions: [...], total, total_kwh, total_huf, limit, offset }
  GET /api/me/sessions/{id}/invoice  → a Számlázz.hu e-számla PDF-je (csak a saját sessionre)

Soha nem ad vissza más e-mail-címhez tartozó töltést: minden lekérdezés a bejelentkezett
identitás (kisbetűs) e-mailjére szűr.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Identity, get_current_identity, get_db
from app.db.models import ChargePoint, ChargeSession, User

router = APIRouter(prefix="/me", tags=["me"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _duration_s(s: ChargeSession) -> Optional[int]:
    if not s.started_at:
        return None
    start = s.started_at if s.started_at.tzinfo else s.started_at.replace(tzinfo=timezone.utc)
    end = s.finished_at or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - start).total_seconds()))


def _status(s: ChargeSession) -> str:
    if s.finished_at is None:
        return "active" if s.ocpp_transaction_id else "waiting"
    if s.ocpp_transaction_id is None:
        return "timed_out"
    return "finished"


def _session_item(s: ChargeSession) -> dict:
    cp = s.charge_point
    loc = cp.location if cp else None
    return {
        "id": s.id,
        "charge_point": {
            "id": cp.id if cp else None,
            "ocpp_id": cp.ocpp_id if cp else None,
            "name": (loc.name if loc else None) or (cp.ocpp_id if cp else None),
            "address": loc.address_text if loc else None,
        },
        "connector_id": s.connector_id,
        "started_at": s.started_at.isoformat() if s.started_at else None,
        "finished_at": s.finished_at.isoformat() if s.finished_at else None,
        "duration_s": _duration_s(s),
        "energy_kwh": round(float(s.energy_kwh), 3) if s.energy_kwh is not None else None,
        "cost_huf": round(float(s.cost_huf)) if s.cost_huf is not None else None,
        "currency": "HUF",
        "status": _status(s),
        "invoice_number": s.invoice_number,
        # A PDF-et a backend adja ki (Bearer kell hozzá), nem egy Számlázz.hu-s publikus link.
        "invoice_url": f"/api/me/sessions/{s.id}/invoice" if s.invoice_number else None,
    }


def _profile_dict(u: Optional[User]) -> Optional[dict]:
    if u is None:
        return None
    return {
        "email": u.email,
        "billing_type": u.billing_type,
        "billing_name": u.billing_name,
        "billing_street": u.billing_street,
        "billing_zip": u.billing_zip,
        "billing_city": u.billing_city,
        "billing_country": u.billing_country,
        "billing_company": u.billing_company,
        "billing_tax_number": u.billing_tax_number,
    }


def _own_sessions_filter(email: str):
    return func.lower(ChargeSession.anonymous_email) == email.strip().lower()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=dict)
@router.get("/", response_model=dict, include_in_schema=False)
async def get_me(
    ident: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(User).where(User.email == ident.email))).scalar_one_or_none()
    return {
        "ok": True,
        "email": ident.email,
        "name": ident.name or (user.billing_name if user else None),
        "auth_source": ident.source,
        "keycloak_linked": bool(user and user.keycloak_sub),
        "is_admin": ident.is_admin,
        "profile": _profile_dict(user),
    }


@router.get("/sessions", response_model=dict)
async def my_sessions(
    ident: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    own = _own_sessions_filter(ident.email)

    totals = (
        await db.execute(
            select(
                func.count(ChargeSession.id),
                func.coalesce(func.sum(ChargeSession.energy_kwh), 0.0),
                func.coalesce(func.sum(ChargeSession.cost_huf), 0.0),
            ).where(own)
        )
    ).one()
    total, total_kwh, total_huf = int(totals[0]), float(totals[1] or 0.0), float(totals[2] or 0.0)

    rows = (
        await db.execute(
            select(ChargeSession)
            .options(selectinload(ChargeSession.charge_point).selectinload(ChargePoint.location))
            .where(own)
            .order_by(desc(ChargeSession.started_at), desc(ChargeSession.id))
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()

    return {
        "ok": True,
        "email": ident.email,
        "sessions": [_session_item(s) for s in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "total_kwh": round(total_kwh, 3),
        "total_huf": round(total_huf),
        "currency": "HUF",
    }


@router.get("/sessions/{session_id}/invoice")
async def my_session_invoice(
    session_id: int,
    ident: Identity = Depends(get_current_identity),
    db: AsyncSession = Depends(get_db),
):
    """A saját töltés e-számlája PDF-ben (Számlázz.hu). Idegen session → 404 (nem 403: ne szivárogjon a létezés)."""
    from app.services.invoice import fetch_invoice_pdf

    s = (
        await db.execute(
            select(ChargeSession).where(ChargeSession.id == session_id, _own_sessions_filter(ident.email))
        )
    ).scalar_one_or_none()
    if s is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    if not s.invoice_number:
        raise HTTPException(status_code=404, detail="no_invoice")

    pdf = await fetch_invoice_pdf(s.invoice_number)
    if not pdf:
        raise HTTPException(status_code=502, detail="invoice_unavailable")

    safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in s.invoice_number)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="szamla_{safe_name}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )
