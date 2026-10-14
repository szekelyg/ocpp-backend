import os
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.db.models import ChargePoint
from app.ocpp.ocpp_utils import MIN_CHARGE_HUF

router = APIRouter(prefix="/charge-points", tags=["charge-points"])

OFFLINE_TTL = timedelta(seconds=120)
# Üzleti minimum (HUF) – közös forrás: ocpp_utils.MIN_CHARGE_HUF
_STRIPE_MIN_HUF = MIN_CHARGE_HUF


def _price_per_kwh() -> float:
    v = os.environ.get("OCPP_PRICE_HUF_PER_KWH")
    try:
        return float(v) if v else 0.0
    except (ValueError, TypeError):
        return 0.0


def compute_status(cp: ChargePoint) -> str:
    if not cp.last_seen_at:
        return "offline"

    now = datetime.now(timezone.utc)

    # Defensive: treat a naive last_seen_at as UTC so we never mix naive/aware
    # (production stores tz-aware UTC; this guards imports/legacy rows).
    last_seen = cp.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)

    if now - last_seen > OFFLINE_TTL:
        # Ha aktívan tölt, ne jelöljük offline-nak csak azért mert nincs heartbeat
        # (töltés közben egyes CP-k nem küldenek rendszeres heartbeat-et)
        if (cp.status or "").lower() == "charging":
            return "charging"
        return "offline"

    return cp.status or "unknown"


def _cp_dict(cp: ChargePoint) -> dict:
    """PUBLIKUS töltő-adat: csak ami a térképhez/indításhoz kell.

    Szándékosan NINCS benne: ocpp_id (a töltő OCPP-azonosítója), a sorszámos DB-id,
    last_seen_at, gyártó/típus, terheléselosztás részletei. Az "id" a stabil, pszeudonim
    public_id (UUID) – ezt viszi a QR (?cp=…) és az intent-indítás is.
    """
    price = _price_per_kwh()
    return {
        "id": cp.public_id,
        "status": compute_status(cp),
        "location_name": cp.location.name if cp.location else None,
        "address_text": cp.location.address_text if cp.location else None,
        "latitude": float(cp.location.latitude) if cp.location and cp.location.latitude is not None else None,
        "longitude": float(cp.location.longitude) if cp.location and cp.location.longitude is not None else None,
        "connector_type": cp.connector_type,
        "max_power_kw": cp.max_power_kw,
        "price_huf_per_kwh": price,
        "min_charge_huf": _STRIPE_MIN_HUF,
        # Csak a tény, hogy közös betáplálású (a vezető fizetés előtt tudja, hogy egyidejű
        # töltésnél a teljesítmény megoszlik) – csoportnév, korlátok, élő állapot NEM.
        "shared_supply": bool(cp.load_group),
    }


def _published():
    return select(ChargePoint).options(selectinload(ChargePoint.location)).where(ChargePoint.is_published.is_(True))


async def resolve_public_charge_point(db: AsyncSession, ref: str) -> Optional[ChargePoint]:
    """Publikált töltő keresése publikus hivatkozással.

    Elfogadott: az új public_id (UUID); visszafelé-kompatibilitásként a régi QR-kódok/linkek
    sorszámos id-ja vagy ocpp_id-ja is. Publikálatlan töltőt sosem ad vissza.
    """
    ref = (ref or "").strip()
    if not ref or len(ref) > 64:
        return None
    cp = (await db.execute(_published().where(ChargePoint.public_id == ref))).scalar_one_or_none()
    if cp is None and ref.isdigit():
        cp = (await db.execute(_published().where(ChargePoint.id == int(ref)))).scalar_one_or_none()
    if cp is None:
        cp = (await db.execute(_published().where(ChargePoint.ocpp_id == ref))).scalar_one_or_none()
    return cp


@router.get("/", response_model=list[dict])
async def list_charge_points(db: AsyncSession = Depends(get_db)):
    """Csak publikált töltők – a konfigurálásra váró / belső teszt töltők nem látszanak."""
    items = (await db.execute(_published())).scalars().all()
    return [_cp_dict(cp) for cp in items]


@router.get("/{ref}", response_model=dict)
async def get_charge_point(ref: str, db: AsyncSession = Depends(get_db)):
    """Egy publikált töltő public_id (vagy régi QR: sorszámos id / ocpp_id) alapján."""
    cp = await resolve_public_charge_point(db, ref)
    if not cp:
        raise HTTPException(status_code=404, detail="ChargePoint not found")
    return _cp_dict(cp)
