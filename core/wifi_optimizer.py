"""
wifi_optimizer.py — Intel Wi-Fi AX211 registry optimizer for NetBoost.

Writes performance-oriented driver parameters to the Network Adapter class
registry key for Intel Wi-Fi adapters.  All writes target HKLM, so
administrator privileges are required.
"""

import logging
import subprocess
import winreg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ADAPTER_CLASS_GUID = "{4D36E972-E325-11CE-BFC1-08002BE10318}"
WIFI_REGISTRY_BASE = rf"SYSTEM\CurrentControlSet\Control\Class\{ADAPTER_CLASS_GUID}"

# Map registry value name -> PreferredBand value -> band label
_BAND_MAP = {
    1: "2.4GHz",
    2: "5GHz",
    3: "6GHz",
}


# ---------------------------------------------------------------------------
# Internal registry helpers
# ---------------------------------------------------------------------------

def _read_reg(subkey: str, value_name: str):
    """
    Read *value_name* from HKLM\\*subkey*.

    Returns the stored value (any type) or ``None`` on any error.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            subkey,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return value
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("wifi_optimizer: cannot read HKLM\\%s\\%s: %s", subkey, value_name, exc)
        return None


def _write_reg(subkey: str, value_name: str, value: int) -> None:
    """Write a DWORD *value* to HKLM\\*subkey*\\*value_name*."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            subkey,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, value)
        logger.info("wifi_optimizer: HKLM\\%s\\%s = %d", subkey, value_name, value)
    except OSError as exc:
        logger.error("wifi_optimizer: cannot write HKLM\\%s\\%s: %s", subkey, value_name, exc)
        raise


def _delete_reg(subkey: str, value_name: str) -> None:
    """Delete *value_name* from HKLM\\*subkey*, ignoring absence."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            subkey,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, value_name)
        logger.info("wifi_optimizer: deleted HKLM\\%s\\%s", subkey, value_name)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("wifi_optimizer: cannot delete HKLM\\%s\\%s: %s", subkey, value_name, exc)


# ---------------------------------------------------------------------------
# Adapter discovery
# ---------------------------------------------------------------------------

def get_wifi_adapter_key() -> str | None:
    """
    Enumerate 4-digit subkeys under WIFI_REGISTRY_BASE and find the first Intel
    Wi-Fi adapter.

    The adapter is identified by its ``DriverDesc`` value containing "Intel"
    and at least one of "Wi-Fi", "Wireless", "AX", or "WiFi".

    Returns the full HKLM subkey path (e.g. ``"SYSTEM\\...\\0002"``) or
    ``None`` if no matching adapter is found.
    """
    try:
        base_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            WIFI_REGISTRY_BASE,
            0,
            winreg.KEY_READ,
        )
    except OSError as exc:
        logger.error("wifi_optimizer: cannot open adapter class key: %s", exc)
        return None

    with base_key:
        idx = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(base_key, idx)
            except OSError:
                break
            idx += 1

            # Only check 4-digit numeric subkeys (e.g. 0000, 0001 …).
            if len(subkey_name) != 4 or not subkey_name.isdigit():
                continue

            full_path = f"{WIFI_REGISTRY_BASE}\\{subkey_name}"
            desc = _read_reg(full_path, "DriverDesc")
            if not isinstance(desc, str):
                continue

            desc_upper = desc.upper()
            is_intel = "INTEL" in desc_upper
            is_wifi  = any(kw in desc_upper for kw in ("WI-FI", "WIFI", "WIRELESS", "AX"))

            if is_intel and is_wifi:
                logger.info("wifi_optimizer: found adapter at '%s': %s", full_path, desc)
                return full_path

    logger.warning("wifi_optimizer: no Intel Wi-Fi adapter found under %s", WIFI_REGISTRY_BASE)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply(settings: dict) -> dict:
    """
    Apply Wi-Fi optimizations described in *settings*.

    Settings keys consumed (all bool):
    - ``disable_power_saving``  — PowerSavingMode=0
    - ``minimize_roaming``      — RoamAggressiveness=1
    - ``max_tx_power``          — TxPowerLevel=5
    - ``disable_bss_scan``      — BSSSelectorCLsupport=0
    - ``prefer_6ghz``           — PreferredBand=3
    - ``throughput_booster``    — Throughput Booster=1
    - ``disable_mimo_power_save`` — MIMO Power Save Mode=3
    - ``disable_lso``           — *LsoV2IPv4=0, *LsoV2IPv6=0 (eliminates LSO-induced ping spikes)
    - ``disable_interrupt_mod`` — InterruptModeration=0 (every packet interrupts CPU immediately)

    Returns a *backup* dict of original values suitable for :func:`restore`.
    """
    backup: dict = {}
    adapter_key = get_wifi_adapter_key()
    if adapter_key is None:
        logger.warning("wifi_optimizer: apply() skipped — no adapter key.")
        backup["_adapter_found"] = False
        return backup

    tweaks: list[tuple[str, int]] = []

    if settings.get("disable_power_saving"):
        tweaks.append(("PowerSavingMode", 0))
    if settings.get("minimize_roaming"):
        tweaks.append(("RoamAggressiveness", 1))
    if settings.get("max_tx_power"):
        tweaks.append(("TxPowerLevel", 5))
    if settings.get("disable_bss_scan"):
        tweaks.append(("BSSSelectorCLsupport", 0))
    if settings.get("prefer_6ghz"):
        tweaks.append(("PreferredBand", 3))
    if settings.get("throughput_booster"):
        tweaks.append(("Throughput Booster", 1))
    if settings.get("disable_mimo_power_save"):
        tweaks.append(("MIMO Power Save Mode", 3))
    if settings.get("disable_lso"):
        # Large Send Offload lets the NIC batch outgoing TCP segments into large
        # frames, which introduces 20–200 ms stalls in game traffic.  Disabling
        # both IPv4 and IPv6 LSO v2 is the single biggest fix for in-game spikes.
        tweaks.append(("*LsoV2IPv4", 0))
        tweaks.append(("*LsoV2IPv6", 0))
    if settings.get("disable_interrupt_mod"):
        # With interrupt moderation enabled the NIC waits up to ~200 μs before
        # raising a CPU interrupt for incoming packets.  Disabling it ensures
        # every packet is delivered to the driver immediately, cutting jitter.
        tweaks.append(("InterruptModeration", 0))

    for value_name, new_val in tweaks:
        backup[value_name] = _read_reg(adapter_key, value_name)
        try:
            _write_reg(adapter_key, value_name, new_val)
        except OSError:
            pass  # already logged inside _write_reg

    backup["_adapter_key"] = adapter_key
    backup["_adapter_found"] = True
    logger.info("wifi_optimizer: %d tweak(s) applied.", len(tweaks))
    return backup


def restore(backup: dict) -> None:
    """
    Restore Wi-Fi registry values from *backup* (as returned by :func:`apply`).

    Values that were absent before are deleted; otherwise the original is
    re-written.
    """
    adapter_key = backup.pop("_adapter_key", None)
    if adapter_key is None:
        adapter_key = get_wifi_adapter_key()
    if adapter_key is None:
        logger.warning("wifi_optimizer: restore() skipped — no adapter key.")
        return

    for value_name, original in backup.items():
        if value_name.startswith("_"):
            continue
        if original is None:
            _delete_reg(adapter_key, value_name)
        else:
            try:
                _write_reg(adapter_key, value_name, int(original))
            except (OSError, TypeError, ValueError):
                pass

    logger.info("wifi_optimizer: registry values restored.")


def get_current_band() -> str:
    """
    Return the currently configured preferred band as a human-readable string.

    Returns ``"2.4GHz"``, ``"5GHz"``, or ``"6GHz"``.  Defaults to ``"2.4GHz"``
    if the value is absent or unrecognised.
    """
    adapter_key = get_wifi_adapter_key()
    if adapter_key is None:
        return "2.4GHz"
    val = _read_reg(adapter_key, "PreferredBand")
    return _BAND_MAP.get(val, "2.4GHz")


def test_latency(host: str = "1.1.1.1") -> float:
    """
    Ping *host* once and return the average round-trip time in milliseconds.

    Returns ``-1.0`` if the ping fails or the output cannot be parsed.
    """
    try:
        result = subprocess.run(
            ["ping", "-n", "4", host],
            capture_output=True,
            text=True,
            timeout=15,
        )
        # Parse "Average = XXms" from Windows ping output.
        import re
        match = re.search(r"Average\s*=\s*(\d+)ms", result.stdout, re.IGNORECASE)
        if match:
            return float(match.group(1))
        logger.warning("wifi_optimizer: could not parse ping output for %s", host)
        return -1.0
    except Exception as exc:
        logger.error("wifi_optimizer: ping failed for %s: %s", host, exc)
        return -1.0


# ---------------------------------------------------------------------------
# WifiOptimizer class — object-oriented wrapper used by the UI
# ---------------------------------------------------------------------------

class WifiOptimizer:
    """Object-oriented interface for Wi-Fi optimization (wraps module functions)."""

    def get_wifi_adapter_key(self) -> str | None:
        return get_wifi_adapter_key()

    def apply(self, settings: dict) -> dict:
        return apply(settings)

    def restore(self, backup: dict) -> None:
        restore(backup)

    def get_current_band(self) -> str:
        return get_current_band()

    def test_latency(self, host: str = "1.1.1.1") -> float:
        return test_latency(host)
