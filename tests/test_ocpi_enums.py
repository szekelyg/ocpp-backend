"""Unit tests for OCPI enum mapping (no DB)."""
from types import SimpleNamespace

from app.ocpi import enums


def test_evse_status_mapping():
    assert enums.evse_status("available") == "AVAILABLE"
    assert enums.evse_status("charging") == "CHARGING"
    assert enums.evse_status("preparing") == "CHARGING"      # occupied
    assert enums.evse_status("suspendedev") == "CHARGING"
    assert enums.evse_status("finishing") == "CHARGING"
    assert enums.evse_status("reserved") == "RESERVED"
    assert enums.evse_status("unavailable") == "INOPERATIVE"
    assert enums.evse_status("faulted") == "OUTOFORDER"
    assert enums.evse_status("offline") == "UNKNOWN"
    assert enums.evse_status(None) == "UNKNOWN"
    assert enums.evse_status("garbage") == "UNKNOWN"


def test_every_internal_status_is_valid_ocpi():
    valid = {v for k, v in vars(enums.EVSEStatus).items() if not k.startswith("_")}
    for internal in ["available", "preparing", "charging", "suspendedev",
                     "suspendedevse", "finishing", "reserved", "unavailable",
                     "faulted", "offline", "unknown"]:
        assert enums.evse_status(internal) in valid


def test_connector_standard():
    assert enums.connector_standard("Type 2") == "IEC_62196_T2"
    assert enums.connector_standard("type2") == "IEC_62196_T2"
    assert enums.connector_standard("CCS2") == "IEC_62196_T2_COMBO"
    assert enums.connector_standard("CHAdeMO") == "CHADEMO"
    assert enums.connector_standard("Type 1") == "IEC_62196_T1"
    assert enums.connector_standard(None) == "IEC_62196_T2"


def test_power_type_and_format():
    dc = enums.connector_standard("CCS2")
    ac = enums.connector_standard("Type 2")
    assert enums.power_type(dc, 50) == "DC"
    assert enums.power_type(ac, 22) == "AC_3_PHASE"
    assert enums.power_type(ac, 3.7) == "AC_1_PHASE"
    assert enums.power_type(ac, 100) == "DC"   # >43kW heuristic
    assert enums.connector_format("DC") == "CABLE"
    assert enums.connector_format("AC_3_PHASE") == "SOCKET"


def test_session_status():
    pending = SimpleNamespace(finished_at=None, ocpp_transaction_id=None)
    active = SimpleNamespace(finished_at=None, ocpp_transaction_id="12")
    completed = SimpleNamespace(finished_at="2026", ocpp_transaction_id="12")
    invalid = SimpleNamespace(finished_at="2026", ocpp_transaction_id=None)
    assert enums.session_status(pending) == "PENDING"
    assert enums.session_status(active) == "ACTIVE"
    assert enums.session_status(completed) == "COMPLETED"
    assert enums.session_status(invalid) == "INVALID"
