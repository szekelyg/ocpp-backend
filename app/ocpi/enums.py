"""OCPI 2.2.1 enums and mapping tables from internal OCPP state.

Only the OCPI-defined values are used here. Note in particular that the OCPI
2.2.1 *EVSE Status* enum has NO ``PREPARING``/``FINISHING`` (those are OCPP
ChargePointStatus values) — they map onto OCPI ``CHARGING``/``AVAILABLE`` below.
"""
from __future__ import annotations

from typing import Optional


# --- OCPI EVSE Status (Status enum) ---------------------------------------
class EVSEStatus:
    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"
    CHARGING = "CHARGING"
    INOPERATIVE = "INOPERATIVE"
    OUTOFORDER = "OUTOFORDER"
    PLANNED = "PLANNED"
    REMOVED = "REMOVED"
    RESERVED = "RESERVED"
    UNKNOWN = "UNKNOWN"


# Internal status string (OCPP status lowercased, or computed "offline") -> OCPI.
# We use an *occupancy* interpretation: a connected/charging vehicle reads as
# CHARGING (occupied) rather than AVAILABLE, so roaming eMSPs don't route a
# driver to a busy stall. "offline" is reported UNKNOWN (we can't vouch for it).
_EVSE_STATUS_MAP = {
    "available": EVSEStatus.AVAILABLE,
    "preparing": EVSEStatus.CHARGING,
    "charging": EVSEStatus.CHARGING,
    "suspendedev": EVSEStatus.CHARGING,
    "suspendedevse": EVSEStatus.CHARGING,
    "finishing": EVSEStatus.CHARGING,
    "reserved": EVSEStatus.RESERVED,
    "unavailable": EVSEStatus.INOPERATIVE,
    "faulted": EVSEStatus.OUTOFORDER,
    "offline": EVSEStatus.UNKNOWN,
    "unknown": EVSEStatus.UNKNOWN,
}


def evse_status(internal_status: Optional[str]) -> str:
    return _EVSE_STATUS_MAP.get((internal_status or "").strip().lower(), EVSEStatus.UNKNOWN)


# --- OCPI Session status (SessionStatus enum) -----------------------------
class SessionStatus:
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    INVALID = "INVALID"
    PENDING = "PENDING"
    RESERVATION = "RESERVATION"


def session_status(cs) -> str:
    """Derive OCPI session status from a ChargeSession row.

    finished + no tx  -> INVALID (waiting-timeout: never started)
    finished          -> COMPLETED
    tx set            -> ACTIVE
    else              -> PENDING (remote start sent, StartTransaction not yet in)
    """
    if cs.finished_at is not None:
        if cs.ocpp_transaction_id is None:
            return SessionStatus.INVALID
        return SessionStatus.COMPLETED
    if cs.ocpp_transaction_id is not None:
        return SessionStatus.ACTIVE
    return SessionStatus.PENDING


# --- OCPI Connector type (ConnectorType enum) -----------------------------
class ConnectorType:
    IEC_62196_T1 = "IEC_62196_T1"
    IEC_62196_T1_COMBO = "IEC_62196_T1_COMBO"
    IEC_62196_T2 = "IEC_62196_T2"
    IEC_62196_T2_COMBO = "IEC_62196_T2_COMBO"
    CHADEMO = "CHADEMO"
    DOMESTIC_F = "DOMESTIC_F"


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower().replace("-", "").replace("_", "").replace(" ", "")


def connector_standard(connector_type: Optional[str]) -> str:
    n = _norm(connector_type)
    if not n:
        return ConnectorType.IEC_62196_T2  # sensible EU default
    if "chademo" in n:
        return ConnectorType.CHADEMO
    if "ccs2" in n or "combo2" in n or "t2combo" in n or "type2combo" in n:
        return ConnectorType.IEC_62196_T2_COMBO
    if "ccs1" in n or "combo1" in n or "t1combo" in n or "type1combo" in n:
        return ConnectorType.IEC_62196_T1_COMBO
    if n in ("type2", "t2", "mennekes", "iec62196t2"):
        return ConnectorType.IEC_62196_T2
    if n in ("type1", "t1", "j1772", "iec62196t1"):
        return ConnectorType.IEC_62196_T1
    if "schuko" in n or "domestic" in n or n in ("typef", "f"):
        return ConnectorType.DOMESTIC_F
    if "ccs" in n:
        return ConnectorType.IEC_62196_T2_COMBO
    if "type2" in n or n.startswith("t2"):
        return ConnectorType.IEC_62196_T2
    return ConnectorType.IEC_62196_T2


# --- OCPI Connector format / Power type -----------------------------------
class ConnectorFormat:
    SOCKET = "SOCKET"
    CABLE = "CABLE"


class PowerType:
    AC_1_PHASE = "AC_1_PHASE"
    AC_3_PHASE = "AC_3_PHASE"
    DC = "DC"


_DC_STANDARDS = {ConnectorType.CHADEMO, ConnectorType.IEC_62196_T2_COMBO, ConnectorType.IEC_62196_T1_COMBO}


def power_type(standard: str, max_power_kw: Optional[float]) -> str:
    """DC connectors -> DC; otherwise AC, 3-phase above ~7.4 kW, else 1-phase.

    Heuristic only — the data model has no explicit AC/DC flag yet.
    """
    if standard in _DC_STANDARDS:
        return PowerType.DC
    if max_power_kw is not None and float(max_power_kw) > 43.0:
        return PowerType.DC
    if max_power_kw is not None and float(max_power_kw) <= 7.4:
        return PowerType.AC_1_PHASE
    return PowerType.AC_3_PHASE


def connector_format(power: str) -> str:
    return ConnectorFormat.CABLE if power == PowerType.DC else ConnectorFormat.SOCKET


# --- OCPI auth / token / authorization / command enums --------------------
class AuthMethod:
    AUTH_REQUEST = "AUTH_REQUEST"
    COMMAND = "COMMAND"
    WHITELIST = "WHITELIST"


class TokenType:
    AD_HOC_USER = "AD_HOC_USER"
    APP_USER = "APP_USER"
    OTHER = "OTHER"
    RFID = "RFID"


class AllowedType:
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    NO_CREDIT = "NO_CREDIT"
    NOT_ALLOWED = "NOT_ALLOWED"


class WhitelistType:
    ALWAYS = "ALWAYS"
    ALLOWED = "ALLOWED"
    ALLOWED_OFFLINE = "ALLOWED_OFFLINE"
    NEVER = "NEVER"


class CommandResponseType:
    ACCEPTED = "ACCEPTED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    REJECTED = "REJECTED"
    UNKNOWN_SESSION = "UNKNOWN_SESSION"


class CommandResultType:
    ACCEPTED = "ACCEPTED"
    CANCELED_RESERVATION = "CANCELED_RESERVATION"
    EVSE_OCCUPIED = "EVSE_OCCUPIED"
    EVSE_INOPERATIVE = "EVSE_INOPERATIVE"
    FAILED = "FAILED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    REJECTED = "REJECTED"
    TIMEOUT = "TIMEOUT"
    UNKNOWN_RESERVATION = "UNKNOWN_RESERVATION"


class CdrDimensionType:
    ENERGY = "ENERGY"
    TIME = "TIME"


class TariffDimensionType:
    ENERGY = "ENERGY"
    FLAT = "FLAT"
    TIME = "TIME"


class Role:
    CPO = "CPO"
    EMSP = "EMSP"
    HUB = "HUB"


class ModuleID:
    CDRS = "cdrs"
    CHARGING_PROFILES = "chargingprofiles"
    COMMANDS = "commands"
    CREDENTIALS = "credentials"
    LOCATIONS = "locations"
    SESSIONS = "sessions"
    TARIFFS = "tariffs"
    TOKENS = "tokens"


class InterfaceRole:
    SENDER = "SENDER"
    RECEIVER = "RECEIVER"
