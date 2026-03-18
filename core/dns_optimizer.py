"""
dns_optimizer.py — Compatibility alias for dns_switcher.

``state_guard.restore_all`` imports ``core.dns_optimizer`` by name.  This
module re-exports everything from :mod:`core.dns_switcher` so that both
import paths work transparently.
"""

from core.dns_switcher import (  # noqa: F401  (re-export)
    DNS_PROVIDERS,
    apply,
    get_active_adapter,
    get_current_dns,
    get_providers,
    restore,
    set_dhcp_dns,
    set_dns,
    _run_netsh,
)
