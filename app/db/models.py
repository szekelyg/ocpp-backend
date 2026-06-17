# app/db/models.py
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, Boolean, JSON, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .base import Base


def utcnow():
    return datetime.now(timezone.utc)


class Organization(Base):
    """Owning party (CPO tenant). The table already exists in the DB (created by
    migration 52ee4f3e419f, never dropped); this ORM class was missing until the
    OCPI work. Referenced by Location.organization_id / ChargePoint.organization_id.
    """
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), unique=True, nullable=False)
    slug = Column(String(255), unique=True, nullable=False)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    locations = relationship("Location", back_populates="organization")


class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)

    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=True)

    name = Column(String(255), nullable=False)
    address_text = Column(String(512), nullable=True)

    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # OCPI identity (CPO). country_code/party_id default to the operator's, but
    # are per-location so a future multi-tenant setup can override them.
    country_code = Column(String(2), nullable=False, default="HU", server_default="HU")
    party_id = Column(String(3), nullable=False, default="ENF", server_default="ENF")
    time_zone = Column(String(64), nullable=False, default="Europe/Budapest", server_default="Europe/Budapest")
    # OCPI last_updated: bumped whenever anything the eMSP sees changes (drives push).
    ocpi_last_updated = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    organization = relationship("Organization", back_populates="locations")
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

    # OCPI EVSE identity. uid is stable (backfilled from ocpp_id); evse_id
    # (HU*ENF*E<id>) is derived in app/ocpi/ids.py.
    ocpi_evse_uid = Column(String(48), nullable=True)
    ocpi_last_updated = Column(DateTime(timezone=True), nullable=True)

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

    # Per-intent árazási felülírás (admin teszt-töltés). NULL = globális env érték.
    price_huf_per_kwh = Column(Float, nullable=True)   # pl. 5 (admin teszt)
    min_charge_huf = Column(Integer, nullable=True)    # pl. 200 (admin teszt, Stripe HUF-min felett)

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

    # OCPI Session/CDR fields. ocpi_session_id defaults to str(id) when emitted;
    # the token/auth fields are set for roaming sessions (OCPI Command / token
    # authorize). Local Stripe/QR sessions leave them NULL → AD_HOC token in CDR.
    ocpi_session_id = Column(String(36), nullable=True, index=True)
    ocpi_last_updated = Column(DateTime(timezone=True), nullable=True)
    ocpi_auth_method = Column(String(16), nullable=True)   # AUTH_REQUEST / COMMAND / WHITELIST
    ocpi_token_uid = Column(String(36), nullable=True)
    ocpi_country_code = Column(String(2), nullable=True)
    ocpi_party_id = Column(String(3), nullable=True)

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


# ---------------------------------------------------------------------------
# OCPI 2.2.1 tables
# ---------------------------------------------------------------------------

class OcpiParty(Base):
    """A registered roaming partner (eMSP/Hub) and our credentials state with it.

    token_incoming = Token C the partner uses to call US (we validate against it).
    token_outgoing = token WE use to call THEM (their Token B/C).
    """
    __tablename__ = "ocpi_parties"
    __table_args__ = (
        UniqueConstraint("role", "country_code", "party_id", name="uq_ocpi_party_identity"),
    )

    id = Column(Integer, primary_key=True, index=True)

    role = Column(String(8), nullable=False)            # partner role: EMSP / HUB
    country_code = Column(String(2), nullable=False)
    party_id = Column(String(3), nullable=False)

    business_name = Column(String(255), nullable=True)
    business_website = Column(String(512), nullable=True)
    business_logo_url = Column(String(512), nullable=True)

    versions_url = Column(String(512), nullable=True)
    version_details_url = Column(String(512), nullable=True)
    endpoints = Column(JSON, nullable=True)             # partner's module endpoints (push targets)

    token_incoming = Column(String(255), nullable=True, index=True)  # Token C (they -> us)
    token_outgoing = Column(String(255), nullable=True)              # token (us -> them)

    status = Column(String(16), nullable=False, default="PENDING")   # PENDING / REGISTERED
    registered_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class OcpiToken(Base):
    """Cached eMSP token (CPO = Receiver of the Tokens module)."""
    __tablename__ = "ocpi_tokens"
    __table_args__ = (
        UniqueConstraint("country_code", "party_id", "uid", "type", name="uq_ocpi_token_identity"),
    )

    id = Column(Integer, primary_key=True, index=True)

    country_code = Column(String(2), nullable=False)
    party_id = Column(String(3), nullable=False)
    uid = Column(String(36), nullable=False, index=True)
    type = Column(String(16), nullable=False)           # RFID / APP_USER / AD_HOC_USER / OTHER
    contract_id = Column(String(36), nullable=False)

    visual_number = Column(String(64), nullable=True)
    issuer = Column(String(64), nullable=True)
    group_id = Column(String(36), nullable=True)
    valid = Column(Boolean, nullable=False, default=True)
    whitelist = Column(String(16), nullable=False, default="NEVER")  # ALWAYS/ALLOWED/ALLOWED_OFFLINE/NEVER
    language = Column(String(2), nullable=True)
    default_profile_type = Column(String(16), nullable=True)
    energy_contract = Column(JSON, nullable=True)
    raw = Column(JSON, nullable=True)                   # full token object as received (round-trips on GET)

    last_updated = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class OcpiCdr(Base):
    """Immutable CDR snapshot (CPO = Sender). Frozen at session completion so a
    later env price change cannot mutate a billed record.
    """
    __tablename__ = "ocpi_cdrs"

    id = Column(Integer, primary_key=True, index=True)
    cdr_id = Column(String(39), nullable=False, unique=True, index=True)

    session_id = Column(Integer, ForeignKey("charge_sessions.id", ondelete="SET NULL"), nullable=True, index=True)

    country_code = Column(String(2), nullable=False)
    party_id = Column(String(3), nullable=False)

    start_date_time = Column(DateTime(timezone=True), nullable=False)
    end_date_time = Column(DateTime(timezone=True), nullable=True)

    cdr_token = Column(JSON, nullable=False)            # frozen CdrToken
    auth_method = Column(String(16), nullable=False)
    cdr_location = Column(JSON, nullable=False)         # frozen CdrLocation
    currency = Column(String(3), nullable=False, default="HUF")
    tariffs = Column(JSON, nullable=True)              # frozen list[Tariff]
    charging_periods = Column(JSON, nullable=True)     # frozen list[ChargingPeriod]

    total_energy = Column(Float, nullable=False, default=0.0)  # kWh
    total_time = Column(Float, nullable=False, default=0.0)    # hours
    total_cost = Column(JSON, nullable=False)           # frozen Price {excl_vat, incl_vat}

    invoice_reference_id = Column(String(64), nullable=True)

    last_updated = Column(DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)

    session = relationship("ChargeSession")


class OcpiCommandResult(Base):
    """Async command audit + idempotency (CPO = Receiver of Commands module)."""
    __tablename__ = "ocpi_command_results"

    id = Column(Integer, primary_key=True, index=True)

    command = Column(String(24), nullable=False)        # START_SESSION / STOP_SESSION / ...
    party_country_code = Column(String(2), nullable=True)
    party_party_id = Column(String(3), nullable=True)
    response_url = Column(String(512), nullable=True)
    request_body = Column(JSON, nullable=True)

    command_response = Column(String(16), nullable=True)  # ACCEPTED / REJECTED / NOT_SUPPORTED / UNKNOWN_SESSION
    command_result = Column(String(24), nullable=True)    # final result posted to response_url

    charge_point_id = Column(Integer, ForeignKey("charge_points.id", ondelete="SET NULL"), nullable=True)
    session_id = Column(Integer, ForeignKey("charge_sessions.id", ondelete="SET NULL"), nullable=True)

    callback_status_code = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)


class OcpiTariff(Base):
    """Thin tariff row (CPO = Sender). Seeded from env pricing; gives CDRs and
    Connectors a stable tariff_id to reference.
    """
    __tablename__ = "ocpi_tariffs"

    id = Column(Integer, primary_key=True, index=True)
    tariff_id = Column(String(36), nullable=False, unique=True, index=True)

    country_code = Column(String(2), nullable=False)
    party_id = Column(String(3), nullable=False)
    currency = Column(String(3), nullable=False, default="HUF")

    elements = Column(JSON, nullable=False)             # frozen list[TariffElement]
    min_price = Column(JSON, nullable=True)
    max_price = Column(JSON, nullable=True)

    last_updated = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)