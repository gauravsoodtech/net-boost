"""
tcp_optimizer.py — Compatibility alias for network_optimizer.

``state_guard.restore_all`` imports ``core.tcp_optimizer`` by name.  This
module re-exports everything from :mod:`core.network_optimizer` so that both
import paths work transparently.
"""

from core.network_optimizer import (  # noqa: F401  (re-export)
    TCP_PARAMS_BASE,
    apply,
    get_interface_guids,
    restore,
    _read_reg,
    _write_reg,
    _delete_reg,
    _restore_value,
)
