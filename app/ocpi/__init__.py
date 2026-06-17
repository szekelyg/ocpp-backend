"""OCPI 2.2.1 CPO-role layer.

Standalone package exposing the network over the Open Charge Point Interface
(OCPI) 2.2.1 protocol in the CPO role. Mounted under ``/ocpi`` (sibling of the
internal ``/api``). See app/ocpi/router.py for the assembled router and
app/core/config.py for the ``OCPI_*`` configuration.
"""

OCPI_VERSION = "2.2.1"
