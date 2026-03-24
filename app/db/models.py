# app/db/models.py
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from .base import Base


def utcnow():
    return datetime.now(timezone.utc)


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)

    name = Column(String(255), nullable=False)
    address_text = Column(String(512), nullable=True)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    charge_points = relationship("ChargePoint", back_populates="location")


class ChargePoint(Base):
    __tablename__ = "charge_points"

    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, nullable=True)
    location_id = Column(Integer, ForeignKey("locations.id", ondelete="SET NULL"), nullable=True)

    ocpp_id = Column(String, unique=True, index=True, nullable=False)

    serial_number = Column(String, nullable=True)
    model = Column(String, nullable=True)
    vendor = Column(String, nullable=True)
    firmware_version = Column(String, nullable=True)

    connector_type = Column(String(64), nullable=True)   # pl. "Type 2", "CCS2", "CHAdeMO"
    max_power_kw = Column(Float, nullable=True)           # pl. 22.0, 50.0

    status = Column(String(32), nullable=False, default="available")
    last_seen_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    location = relationship("Location", back_populates="charge_points")

    sessions = relationship(
        "ChargeSession",
        back_populates="charge_point",
        cascade="all, delete-orphan",
    )

    samples = relationship(
        "MeterSample",
        back_populates="charge_point",
        cascade="all, delete-orphan",
    )

    intents = relationship(
        "ChargingIntent",
        back_populates="charge_point",
        cascade="all, delete-orphan",
    )

class ChargingIntent(Base):
    """
    Fizetés előtti állapot (Stripe/egyéb provider előtt vagy alatt).
    Cél: stabil, később is bővíthető (provider-független mezőkkel).
    """
    __tablename__ = "charging_intents"

    id = Column(Integer, primary_key=True, index=True)

    charge_point_id = Column(
        Integer, ForeignKey("charge_points.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connector_id = Column(Integer, nullable=False, default=1)

    # login nélkül is: email kötelező, később OTP-hez is jó
    anonymous_email = Column(String(255), nullable=False, index=True)

    # pending_payment / paid / expired / cancelled / failed
    status = Column(String(32), nullable=False, default="pending_payment", index=True)

    # választott hold (HUF)
    hold_amount_huf = Column(Integer, nullable=False, default=5000)

    # provider-független mezők (Stripe = "stripe", később lehet "barion", "paypal"...)
    payment_provider = Column(String(32), nullable=True)        # pl. "stripe"
    payment_provider_ref = Column(String(255), nullable=True, index=True)  # pl. checkout_session_id vagy payment_intent_id

    # Számlázási adatok – felhasználó által megadva az intent létrehozásakor
    billing_type = Column(String(16), nullable=True)          # "personal" | "business"
    billing_company = Column(String(255), nullable=True)      # cégnév (csak business)
    billing_tax_number = Column(String(64), nullable=True)    # adószám (csak business)

    # Számlázási adatok – felhasználó adja meg a saját felületünkön
    billing_name = Column(String(255), nullable=True)
    billing_street = Column(String(255), nullable=True)
    billing_zip = Column(String(16), nullable=True)
    billing_city = Column(String(128), nullable=True)
    billing_country = Column(String(4), nullable=True)

    # Stripe PaymentIntent ID – manual capture flow-hoz
    stripe_payment_intent_id = Column(String(255), nullable=True, index=True)

    # opcionális: miért lett cancelled/failed (debug/support)
    cancel_reason = Column(String(64), nullable=True)
    last_error = Column(String(255), nullable=True)

    # 15 perc után automatikusan expire
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    # kapcsolatok
    charge_point = relationship("ChargePoint", back_populates="intents")
    session = relationship("ChargeSession", back_populates="intent", uselist=False)

class ChargeSession(Base):
    __tablename__ = "charge_sessions"

    id = Column(Integer, primary_key=True, index=True)

    charge_point_id = Column(Integer, ForeignKey("charge_points.id", ondelete="CASCADE"), nullable=False, index=True)

    connector_id = Column(Integer, nullable=True)  # pl. 1,2,3...
    ocpp_transaction_id = Column(String, unique=True, nullable=True)
    user_tag = Column(String, nullable=True)

    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    meter_start_wh = Column(Float, nullable=True)
    meter_stop_wh = Column(Float, nullable=True)

    energy_kwh = Column(Float, nullable=True)
    cost_huf = Column(Float, nullable=True)

    # ÚJ ownership + fizetéshez kötés (MVP login nélkül)
    anonymous_email = Column(String(255), nullable=True)
    # unique=True: egy intenthez csak egy session jöhet létre (race condition védelem)
    intent_id = Column(Integer, ForeignKey("charging_intents.id", ondelete="SET NULL"), nullable=True, unique=True, index=True)
    stop_code_hash = Column(String(255), nullable=True)
    invoice_number = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    charge_point = relationship("ChargePoint", back_populates="sessions")
    intent = relationship("ChargingIntent", back_populates="session")

    samples = relationship(
        "MeterSample",
        back_populates="session",
    )


class MeterSample(Base):
    __tablename__ = "meter_samples"

    id = Column(Integer, primary_key=True, index=True)

    charge_point_id = Column(Integer, ForeignKey("charge_points.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("charge_sessions.id", ondelete="SET NULL"), nullable=True, index=True)

    connector_id = Column(Integer, nullable=True)

    ts = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    energy_wh_total = Column(Float, nullable=True)
    power_w = Column(Float, nullable=True)
    current_a = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    charge_point = relationship("ChargePoint", back_populates="samples")
    session = relationship("ChargeSession", back_populates="samples")