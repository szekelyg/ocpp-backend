# app/ocpp/ocpp_ws.py
"""
Kompatibilitási wrapper.

A projektben több helyről lehet import:
- from app.ocpp.ocpp_ws import handle_ocpp
- from app.ocpp.ocpp_ws import remote_start_transaction

A tényleges logika modulokra bontva van:
- app.ocpp.ws
- app.ocpp.registry
- app.ocpp.handlers.*
"""

from app.ocpp.ws import handle_ocpp
from app.ocpp.registry import remote_start_transaction, remote_stop_transaction