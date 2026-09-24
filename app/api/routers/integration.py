# app/api/routers/integration.py
"""Szűk integrációs API más Energiafelhő-rendszereknek (2026-09-24, elszámolás 2.0 / D lépés).

Első fogyasztó: az energiaközösségi platform (ek, app.energiafelho.hu), amely a töltőket
mérési pontok ALMÉRŐJEKÉNT mutatja. Csak ennyit ad ki:

  GET /api/integration/charge-points                      töltőlista a legördülőhöz
  GET /api/integration/charge-points/{id}/negyedorak      negyedórás energia (Wh)

Hozzáférés: Keycloak (realm `ugyfelek`) **service-account** access token, client-credentials
grant, amelyben a `KEYCLOAK_INTEGRATION_ROLE` realm-szerep (alap `ek-integracio`) szerepel,
és a tokent kérő kliens (`azp`) a `KEYCLOAK_INTEGRATION_CLIENTS` listában van (alap
`ek-integracio`). Szándékosan NEM az `ev-admin` szerep: az ek-nak nem kell (és nem is
kaphat) hozzáférést a töltésekhez, e-mail-címekhez, számlákhoz. Személyes adat itt nincs.
A kliens és a szerep a platform-repó `keycloak/scripts/apply-ek-integracio.sh`-jával jön
létre; részletek: docs/KEYCLOAK.md, 8. szakasz.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.api.routers.charge_points import compute_status
from app.db.models import ChargePoint, ChargeSession, MeterSample
from app.services.negyedorak import (
    NEGYEDORA_S,
    SessionAdat,
    negyedora_fel,
    negyedora_le,
    negyedoras_energia,
)

logger = logging.getLogger("integration")

router = APIRouter(prefix="/integration", tags=["integration"])

INTEGRATION_ROLE_DEFAULT = "ek-integracio"
INTEGRATION_CLIENTS_DEFAULT = "ek-integracio"
MAX_ABLAK_S = 31 * 24 * 3600


def integration_role() -> str:
    return (os.environ.get("KEYCLOAK_INTEGRATION_ROLE") or INTEGRATION_ROLE_DEFAULT).strip() or INTEGRATION_ROLE_DEFAULT


def integration_clients() -> frozenset[str]:
    """Engedélyezett `azp`-k. Üres env-érték (`KEYCLOAK_INTEGRATION_CLIENTS=`) = nincs azp-szűrés,
    csak a szerep számít; hiányzó env = az alapértelmezett `ek-integracio`."""
    raw = os.environ.get("KEYCLOAK_INTEGRATION_CLIENTS")
    if raw is None:
        raw = INTEGRATION_CLIENTS_DEFAULT
    return frozenset(x.strip() for x in raw.replace(" ", ",").split(",") if x.strip())


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def verify_integration(authorization: Optional[str] = Header(None)) -> str:
    """Keycloak service-account Bearer az integrációs szereppel. Visszaadja az azp-t (naplóhoz)."""
    from app.services import keycloak

    if not keycloak.enabled():
        # Fail-closed: Keycloak nélkül ez az API nem érhető el (nincs Basic vész-út).
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="integration_not_configured")
    if not authorization:
        raise _unauthorized("missing_bearer_token")
    scheme, _, value = authorization.strip().partition(" ")
    value = value.strip()
    if scheme.lower() != "bearer" or not value:
        raise _unauthorized("unsupported_auth_scheme")
    try:
        ident = await keycloak.verify_access_token(value)
    except keycloak.KeycloakAuthError as e:
        logger.info("integration: token elutasítva: %s", e.reason)
        raise _unauthorized(f"keycloak_{e.reason}")
    role = integration_role()
    if role not in ident.realm_roles:
        logger.warning("integration: nincs '%s' szerep (sub=%s azp=%s)", role, ident.sub, ident.azp)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="integration_role_missing")
    clients = integration_clients()
    if clients and ident.azp not in clients:
        logger.warning("integration: nem engedélyezett kliens azp=%s (sub=%s)", ident.azp, ident.sub)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="integration_client_not_allowed")
    return ident.azp or ident.sub


def _nev(cp: ChargePoint) -> str:
    if cp.location and cp.location.name:
        return f"{cp.location.name} ({cp.ocpp_id})"
    return cp.ocpp_id


@router.get("/charge-points")
async def list_charge_points(
    _azp: str = Depends(verify_integration),
    db: AsyncSession = Depends(get_db),
):
    """Minden töltő (publikált és még konfigurálásra váró is) – csak a legördülőhöz kellő mezők.

    `id` = az OCPP-azonosító (pl. `nograd_var_1`): stabil, a töltő maga küldi, ember is
    felismeri; az ek ezt tárolja `kulso_azonosito`-ként.
    """
    rows = (
        await db.execute(select(ChargePoint).options(selectinload(ChargePoint.location)).order_by(ChargePoint.ocpp_id))
    ).scalars().all()
    out = []
    for cp in rows:
        allapot = compute_status(cp)
        out.append({
            "id": cp.ocpp_id,
            "nev": _nev(cp),
            "helyszin": cp.location.name if cp.location else None,
            "cim": cp.location.address_text if cp.location else None,
            "max_power_kw": cp.max_power_kw,
            "online": allapot != "offline",
            "allapot": allapot,
            "publikalt": bool(cp.is_published),
        })
    return out


@router.get("/charge-points/{cp_id}/negyedorak")
async def charge_point_negyedorak(
    cp_id: str,
    tol: int = Query(..., alias="from", description="unix mp, lefelé 900-ra igazítjuk"),
    ig: int = Query(..., alias="to", description="unix mp (kizáró), felfelé 900-ra igazítjuk"),
    _azp: str = Depends(verify_integration),
    db: AsyncSession = Depends(get_db),
):
    """Negyedórás energia (Wh) a töltő OCPP-méréseiből. Lásd app/services/negyedorak.py.

    - Negyedóra-kulcs: a negyedóra KEZDETE, unix mp, 900-zal osztható (az ek konvenciója).
    - Csak LEZÁRT negyedóra jön: az `to` legfeljebb a folyó negyedóra eleje.
    - Ahol nincs adat (nincs töltés / nincs mérés), ott nincs sor – nem 0.
    - Ablak legfeljebb 31 nap.
    """
    a = negyedora_le(tol)
    most = time.time()
    b = min(negyedora_fel(ig), negyedora_le(most))
    if ig <= tol:
        raise HTTPException(status_code=400, detail="invalid_window")
    if negyedora_fel(ig) - a > MAX_ABLAK_S:
        raise HTTPException(status_code=400, detail="window_too_large")

    cp = (await db.execute(select(ChargePoint).where(ChargePoint.ocpp_id == cp_id))).scalar_one_or_none()
    if cp is None:
        raise HTTPException(status_code=404, detail="charge_point_not_found")

    sorok: list[dict] = []
    if b > a:
        a_dt = datetime.fromtimestamp(a, tz=timezone.utc)
        b_dt = datetime.fromtimestamp(b, tz=timezone.utc)
        sessions = (
            await db.execute(
                select(ChargeSession)
                .where(
                    and_(
                        ChargeSession.charge_point_id == cp.id,
                        ChargeSession.started_at < b_dt,
                        or_(ChargeSession.finished_at.is_(None), ChargeSession.finished_at > a_dt),
                    )
                )
                .order_by(ChargeSession.started_at)
            )
        ).scalars().all()

        mintak_by_session: dict[int, list] = {s.id: [] for s in sessions}
        if sessions:
            res = await db.execute(
                select(MeterSample.session_id, MeterSample.ts, MeterSample.energy_wh_total)
                .where(
                    and_(
                        MeterSample.session_id.in_(list(mintak_by_session)),
                        MeterSample.energy_wh_total.isnot(None),
                    )
                )
                .order_by(MeterSample.ts)
            )
            for sid, ts, wh in res.all():
                mintak_by_session[sid].append((ts, wh))

        adatok = [
            SessionAdat(
                started_at=s.started_at,
                finished_at=s.finished_at,
                meter_start_wh=s.meter_start_wh,
                energy_kwh=s.energy_kwh,
                mintak=mintak_by_session.get(s.id, []),
            )
            for s in sessions
        ]
        for q, (wh, modszer) in negyedoras_energia(adatok, tol=a, ig=b, most=most).items():
            sorok.append({"ts": q, "wh": round(wh, 1), "modszer": modszer})

    return {
        "id": cp.ocpp_id,
        "from": a,
        "to": max(a, b),
        "negyedora_s": NEGYEDORA_S,
        "egyseg": "Wh",
        "negyedorak": sorok,
    }
