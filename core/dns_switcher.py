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
import winreg

import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DNS provider presets
# ---------------------------------------------------------------------------

DNS_PROVIDERS: dict[str, dict | None] = {
    "cloudflare": {"primary": "1.1.1.1",         "secondary": "1.0.0.1"},
    "google":     {"primary": "8.8.8.8",          "secondary": "8.8.4.4"},
    "quad9":      {"primary": "9.9.9.9",          "secondary": "149.112.112.112"},
    "opendns":    {"primary": "208.67.222.222",   "secondary": "208.67.220.220"},
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

    Uses the registry (locale-independent) as the primary source, with
    netsh parsing as a fallback.
    """
    result = _get_dns_from_registry(adapter)
    if result is not None:
        return result

    # Fallback: parse netsh output (locale-dependent for DHCP detection).
    return _get_dns_from_netsh(adapter)


def _get_dns_from_registry(adapter: str) -> dict | None:
    """
    Read DNS config from the registry for *adapter*.

    Searches interface GUID keys for one whose adapter name matches.
    Returns None if the adapter cannot be found in the registry.
    """
    _INTERFACES_KEY = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _INTERFACES_KEY) as root:
            i = 0
            while True:
                try:
                    guid = winreg.EnumKey(root, i)
                    i += 1
                except OSError:
                    break
                subkey_path = f"{_INTERFACES_KEY}\\{guid}"
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path) as sk:
                        # Match adapter by checking if the IP address on this
                        # interface key corresponds to the named adapter.
                        # Read the static NameServer value (comma-separated IPs).
                        try:
                            name_server, _ = winreg.QueryValueEx(sk, "NameServer")
                        except OSError:
                            name_server = ""

                        try:
                            dhcp_name_server, _ = winreg.QueryValueEx(sk, "DhcpNameServer")
                        except OSError:
                            dhcp_name_server = ""

                        # We need to verify this GUID belongs to our adapter.
                        # Match via IP address from psutil.
                        try:
                            ip_addr, _ = winreg.QueryValueEx(sk, "DhcpIPAddress")
                        except OSError:
                            try:
                                ip_addr, _ = winreg.QueryValueEx(sk, "IPAddress")
                                if isinstance(ip_addr, list):
                                    ip_addr = ip_addr[0] if ip_addr else ""
                            except OSError:
                                ip_addr = ""

                        if not ip_addr or ip_addr == "0.0.0.0":
                            continue

                        # Check if this IP belongs to the requested adapter.
                        iface_addrs = psutil.net_if_addrs().get(adapter, [])
                        adapter_ips = {
                            a.address for a in iface_addrs
                            if a.family == socket.AF_INET
                        }
                        if ip_addr not in adapter_ips:
                            continue

                        # Found the matching interface.
                        # Empty NameServer = DHCP mode.
                        is_dhcp = not name_server.strip()
                        if is_dhcp:
                            servers = [s.strip() for s in dhcp_name_server.split(",") if s.strip()]
                        else:
                            servers = [s.strip() for s in name_server.split(",") if s.strip()]

                        return {
                            "primary": servers[0] if len(servers) > 0 else "",
                            "secondary": servers[1] if len(servers) > 1 else "",
                            "is_dhcp": is_dhcp,
                        }
                except OSError:
                    continue
    except OSError as exc:
        logger.debug("Registry DNS lookup failed: %s", exc)

    return None


def _get_dns_from_netsh(adapter: str) -> dict:
    """Fallback: parse netsh output (locale-dependent DHCP detection)."""
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
        "primary": servers[0] if len(servers) > 0 else "",
        "secondary": servers[1] if len(servers) > 1 else "",
        "is_dhcp": is_dhcp,
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


def benchmark_dns_providers(
    domains: list[str] | None = None,
    repeats: int = 3,
) -> list[dict]:
    """
    Benchmark DNS resolution speed for each provider.

    Resolves *domains* via each provider's primary server and measures
    average resolution time.  Returns a list sorted fastest-first::

        [{"provider": "cloudflare", "avg_ms": 12.3, "failures": 0}, ...]

    Uses ``nslookup`` with a specific server to bypass the system resolver.
    """
    import time

    if domains is None:
        domains = ["riot.com", "steampowered.com", "epicgames.com", "battlenet.com"]

    results: list[dict] = []
    for name, info in DNS_PROVIDERS.items():
        if info is None:
            continue  # skip "custom"
        server = info["primary"]
        total_ms = 0.0
        failures = 0
        attempts = 0

        for domain in domains:
            for _ in range(repeats):
                attempts += 1
                try:
                    t0 = time.perf_counter()
                    subprocess.run(
                        ["nslookup", domain, server],
                        capture_output=True, text=True, timeout=5,
                    )
                    elapsed = (time.perf_counter() - t0) * 1000.0
                    total_ms += elapsed
                except (subprocess.TimeoutExpired, Exception):
                    failures += 1

        successful = attempts - failures
        avg_ms = round(total_ms / successful, 1) if successful > 0 else 9999.0
        results.append({
            "provider": name,
            "avg_ms": avg_ms,
            "failures": failures,
        })

    results.sort(key=lambda r: r["avg_ms"])
    return results


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
