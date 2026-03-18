"""
dns_switcher.py — DNS switching via netsh for NetBoost.

Detects the active network adapter, reads its current DNS configuration, and
can apply preset or custom DNS servers.  All operations use subprocess calls
to 'netsh interface ip' so no third-party network libraries are required.

Provides both a :class:`DnsSwitcher` convenience class and module-level
functions (used by state_guard / dns_optimizer).

Requires administrator privileges for set operations.
"""

import logging
import re
import socket
import subprocess

import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DNS provider presets
# ---------------------------------------------------------------------------

DNS_PROVIDERS: dict[str, dict | None] = {
    "cloudflare": {"primary": "1.1.1.1",       "secondary": "1.0.0.1"},
    "google":     {"primary": "8.8.8.8",        "secondary": "8.8.4.4"},
    "quad9":      {"primary": "9.9.9.9",        "secondary": "149.112.112.112"},
    "custom":     None,
}


# ---------------------------------------------------------------------------
# DnsSwitcher class
# ---------------------------------------------------------------------------

class DnsSwitcher:
    """
    Object-oriented interface for DNS switching.

    All methods delegate to module-level functions but are also individually
    overrideable (useful for testing via ``instance.method = MagicMock(...)``).
    """

    DNS_PROVIDERS = DNS_PROVIDERS

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def get_providers(self) -> list[str]:
        """Return the list of available DNS provider names."""
        return get_providers()

    def get_active_adapter(self) -> str:
        """
        Return the name of the active network adapter.

        Raises :class:`RuntimeError` if no suitable adapter is found.
        """
        return get_active_adapter()

    def get_current_dns(self, adapter: str) -> dict:
        """
        Return the current DNS configuration of *adapter*.

        Returns ``{"primary": str, "secondary": str, "is_dhcp": bool}``.
        """
        return get_current_dns(adapter)

    def set_dns(self, adapter: str, primary: str, secondary: str) -> None:
        """Apply static DNS *primary* and *secondary* to *adapter*."""
        set_dns(adapter, primary, secondary)

    def set_dhcp_dns(self, adapter: str) -> None:
        """Revert *adapter* DNS to DHCP-assigned."""
        set_dhcp_dns(adapter)

    def _run_netsh(self, args: list) -> str:
        """Run ``netsh`` with *args*; raises on non-zero exit."""
        return _run_netsh(args)

    # ------------------------------------------------------------------
    # High-level apply / restore
    # ------------------------------------------------------------------

    def apply(
        self,
        provider: str,
        adapter: str = None,
        custom_primary: str = None,
        custom_secondary: str = None,
    ) -> dict:
        """
        Apply DNS settings and return a backup dict.

        The backup uses key ``"original_dns"`` for the pre-change config.
        """
        if provider not in DNS_PROVIDERS:
            raise ValueError(f"Unknown DNS provider '{provider}'. "
                             f"Available: {list(DNS_PROVIDERS)}")

        if adapter is None:
            adapter = self.get_active_adapter()

        backup = {
            "adapter":      adapter,
            "original_dns": self.get_current_dns(adapter),
        }

        if provider == "custom":
            if not custom_primary:
                raise ValueError("custom_primary must be supplied when provider='custom'.")
            primary   = custom_primary
            secondary = custom_secondary or ""
        else:
            info      = DNS_PROVIDERS[provider]
            primary   = info["primary"]
            secondary = info["secondary"]

        self.set_dns(adapter, primary, secondary)
        logger.info("DNS switched to '%s' on adapter '%s'.", provider, adapter)
        return backup

    def restore(self, backup: dict) -> None:
        """
        Restore DNS settings from *backup*.

        Accepts both ``"original_dns"`` (class API) and ``"previous"``
        (module-level API) as the DNS config key.
        """
        adapter = backup.get("adapter")
        if not adapter:
            logger.warning("DNS restore: no adapter in backup; skipping.")
            return

        dns_info = backup.get("original_dns") or backup.get("previous") or {}

        if dns_info.get("is_dhcp"):
            self.set_dhcp_dns(adapter)
        else:
            primary   = dns_info.get("primary", "")
            secondary = dns_info.get("secondary", "")
            if primary:
                self.set_dns(adapter, primary, secondary)
            else:
                self.set_dhcp_dns(adapter)

        logger.info("DNS restored for adapter '%s'.", adapter)


# ---------------------------------------------------------------------------
# Module-level helpers (used by dns_optimizer.py / state_guard.py)
# ---------------------------------------------------------------------------

def _run_netsh(args: list) -> str:
    """
    Run ``netsh`` with *args* and return stdout as a string.

    Raises :class:`subprocess.CalledProcessError` on non-zero exit.
    """
    cmd = ["netsh"] + [str(a) for a in args]
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=err)
    return result.stdout


def get_active_adapter() -> str:
    """
    Return the name of the active network adapter (the one with a default route).

    Prefers Wi-Fi adapters when multiple up adapters are found with addresses.
    Falls back to the first up adapter that has an IPv4 address.

    Raises :class:`RuntimeError` if no suitable adapter is found.
    """
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()

    candidates: list[str] = []
    for name, stat in stats.items():
        if not stat.isup:
            continue
        iface_addrs = addrs.get(name, [])
        has_ipv4 = any(
            a.family == socket.AF_INET and a.address and a.address != "0.0.0.0"
            for a in iface_addrs
        )
        if has_ipv4:
            candidates.append(name)

    if not candidates:
        raise RuntimeError("No active network adapter found.")

    wifi_keywords = ("wi-fi", "wifi", "wireless", "wlan", "802.11")
    for name in candidates:
        if any(kw in name.lower() for kw in wifi_keywords):
            logger.debug("Preferred Wi-Fi adapter: '%s'", name)
            return name

    logger.debug("Using first active adapter: '%s'", candidates[0])
    return candidates[0]


def get_current_dns(adapter: str) -> dict:
    """
    Return the current DNS configuration of *adapter*.

    Returns ``{"primary": str, "secondary": str, "is_dhcp": bool}``.
    """
    try:
        output = _run_netsh(["interface", "ip", "show", "dns", f'name="{adapter}"'])
    except subprocess.CalledProcessError as exc:
        logger.warning("Could not query DNS for adapter '%s': %s", adapter, exc)
        return {"primary": "", "secondary": "", "is_dhcp": True}

    is_dhcp = False
    servers: list[str] = []

    for line in output.splitlines():
        line_lower = line.lower()
        if "dhcp" in line_lower:
            is_dhcp = True
        ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", line)
        if ip_match:
            servers.append(ip_match.group(1))

    return {
        "primary":   servers[0] if len(servers) > 0 else "",
        "secondary": servers[1] if len(servers) > 1 else "",
        "is_dhcp":   is_dhcp,
    }


def set_dns(adapter: str, primary: str, secondary: str) -> None:
    """Apply static DNS servers *primary* and *secondary* to *adapter*."""
    _run_netsh([
        "interface", "ip", "set", "dns",
        f'name="{adapter}"', "static", primary, "primary",
    ])
    logger.info("Set primary DNS %s on '%s'.", primary, adapter)

    if secondary:
        _run_netsh([
            "interface", "ip", "add", "dns",
            f'name="{adapter}"', secondary, "index=2",
        ])
        logger.info("Set secondary DNS %s on '%s'.", secondary, adapter)


def set_dhcp_dns(adapter: str) -> None:
    """Revert *adapter* DNS to DHCP-assigned."""
    _run_netsh(["interface", "ip", "set", "dns", f'name="{adapter}"', "dhcp"])
    logger.info("Reverted DNS to DHCP on '%s'.", adapter)


def get_providers() -> list[str]:
    """Return the list of available DNS provider names."""
    return list(DNS_PROVIDERS.keys())


def apply(
    provider: str,
    adapter: str = None,
    custom_primary: str = None,
    custom_secondary: str = None,
) -> dict:
    """
    Apply DNS settings from *provider* to *adapter* (module-level API).

    Returns a backup dict with key ``"previous"`` for the pre-change config.
    """
    return DnsSwitcher().apply(
        provider,
        adapter=adapter,
        custom_primary=custom_primary,
        custom_secondary=custom_secondary,
    )


def restore(backup: dict) -> None:
    """Restore DNS settings from *backup* (module-level API)."""
    DnsSwitcher().restore(backup)
