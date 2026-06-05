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

# Current Intel AX211 drivers expose "Preferred Band" as
# RoamingPreferredBandType. Older drivers used PreferredBand.
_ROAMING_BAND_MAP = {
    0: "No Preference",
    1: "2.4GHz",
    2: "5GHz",
    3: "6GHz",
    4: "5GHz + 6GHz",
}

_LEGACY_BAND_MAP = {
    1: "2.4GHz",
    2: "5GHz",
    3: "6GHz",
}


def _new_apply_metadata(adapter_found: bool) -> dict:
    """Return diagnostic fields stored alongside the restore backup."""
    return {
        "_adapter_found": adapter_found,
        "_attempted_values": [],
        "_verified_values": [],
        "_failed_values": [],
        "_unsupported_values": [],
        "_write_count": 0,
        "_verified_count": 0,
        "_failed_count": 0,
        # Driver only re-reads these advanced params on a miniport reset.
        # _changed_count counts verified writes whose value actually changed;
        # _requires_restart tells the UI to power-cycle the adapter so the
        # new values go live (a raw registry write alone does NOT take effect).
        "_changed_count": 0,
        "_requires_restart": False,
        "_driver_desc": None,
    }


def _values_match(actual, expected: int) -> bool:
    """Return True when a read-back registry value matches the requested int."""
    try:
        return int(actual) == int(expected)
    except (TypeError, ValueError):
        return False


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
    - ``minimize_roaming``      — RoamAggressiveness=0
    - ``max_tx_power``          — IbssTxPower=100, TxPowerLevel=5
    - ``disable_bss_scan``      — BSSSelectorCLsupport=0
    - ``prefer_6ghz``           — RoamingPreferredBandType=3, PreferredBand=3
    - ``throughput_booster``    — ThroughputBoosterEnabled=1, Throughput Booster=1
    - ``disable_mimo_power_save`` — MIMOPowerSaveMode=3, MIMO Power Save Mode=3
    - ``disable_lso``           — *LsoV2IPv4=0, *LsoV2IPv6=0 (eliminates LSO-induced ping spikes)
    - ``disable_interrupt_mod`` — InterruptModeration=0 (every packet interrupts CPU immediately)

    Returns a *backup* dict of original values suitable for :func:`restore`.
    Diagnostic keys prefixed with ``_`` describe attempted, verified, failed,
    and unsupported driver values.
    """
    backup: dict = _new_apply_metadata(adapter_found=False)
    adapter_key = get_wifi_adapter_key()
    if adapter_key is None:
        logger.warning("wifi_optimizer: apply() skipped — no adapter key.")
        return backup

    tweaks: list[tuple[str, int]] = []

    if settings.get("disable_power_saving"):
        tweaks.append(("PowerSavingMode", 0))
    if settings.get("minimize_roaming"):
        tweaks.append(("RoamAggressiveness", 0))
    if settings.get("max_tx_power"):
        tweaks.append(("IbssTxPower", 100))
        tweaks.append(("TxPowerLevel", 5))
    if settings.get("disable_bss_scan"):
        tweaks.append(("BSSSelectorCLsupport", 0))
    if settings.get("prefer_6ghz"):
        supports_current = _read_reg(adapter_key, "RoamingPreferredBandType") is not None
        supports_legacy = _read_reg(adapter_key, "PreferredBand") is not None
        if supports_current:
            tweaks.append(("RoamingPreferredBandType", 3))
        if supports_legacy:
            tweaks.append(("PreferredBand", 3))
        if not supports_current and not supports_legacy:
            logger.warning(
                "wifi_optimizer: adapter does not expose PreferredBand — "
                "6GHz preference skipped (adapter may not support WiFi 6E)."
            )
            backup["_6ghz_unsupported"] = True
            backup["_unsupported_values"].extend(["RoamingPreferredBandType", "PreferredBand"])
    if "throughput_booster" in settings:
        throughput_value = 1 if settings.get("throughput_booster") else 0
        tweaks.append(("ThroughputBoosterEnabled", throughput_value))
        tweaks.append(("Throughput Booster", throughput_value))
    if settings.get("disable_mimo_power_save"):
        tweaks.append(("MIMOPowerSaveMode", 3))
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
        backup["_attempted_values"].append(value_name)
        backup["_write_count"] += 1
        try:
            _write_reg(adapter_key, value_name, new_val)
        except OSError as exc:
            backup["_failed_values"].append({
                "name": value_name,
                "target": new_val,
                "actual": backup[value_name],
                "reason": f"write failed: {exc}",
            })
            continue

        actual = _read_reg(adapter_key, value_name)
        if _values_match(actual, new_val):
            backup["_verified_values"].append(value_name)
            backup["_verified_count"] += 1
            # Old value differs from the new one → the driver's cached config
            # is now stale and needs a restart to pick this up.
            if not _values_match(backup[value_name], new_val):
                backup["_changed_count"] += 1
        else:
            backup["_failed_values"].append({
                "name": value_name,
                "target": new_val,
                "actual": actual,
                "reason": "readback mismatch",
            })

    backup["_adapter_key"] = adapter_key
    backup["_adapter_found"] = True
    backup["_failed_count"] = len(backup["_failed_values"])
    backup["_driver_desc"] = _read_reg(adapter_key, "DriverDesc")
    backup["_requires_restart"] = backup["_changed_count"] > 0
    logger.info(
        "wifi_optimizer: %d tweak(s) applied, %d changed (restart=%s).",
        len(tweaks), backup["_changed_count"], backup["_requires_restart"],
    )
    return backup


def restore(backup: dict) -> None:
    """
    Restore Wi-Fi registry values from *backup* (as returned by :func:`apply`).

    Values that were absent before are deleted; otherwise the original is
    re-written.
    """
    adapter_key = backup.get("_adapter_key")
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


def restart_adapter(driver_desc: str | None = None) -> dict:
    """
    Power-cycle the Intel Wi-Fi adapter so the driver re-reads its registry
    config.

    The advanced parameters written by :func:`apply` (LSO, InterruptModeration,
    PowerSavingMode, TxPower, …) are only read by the miniport driver at init
    time — a raw registry write does NOT take effect until the adapter is reset.
    This restart is what actually makes the anti-jitter tweaks go live.

    Briefly drops the Wi-Fi link (~5-10 s); Windows auto-reconnects to the known
    SSID afterwards.  Admin is required (already held by the app).

    Returns ``{"ok": bool, "error": str}``.  Never raises — a failed or timed-out
    restart is reported via ``ok=False`` so the caller can fall back to telling
    the user to disable/enable the adapter manually (or reboot).
    """
    if driver_desc:
        safe = str(driver_desc).replace("'", "''")
        ps = f"Restart-NetAdapter -InterfaceDescription '{safe}' -Confirm:$false"
    else:
        ps = (
            "Get-NetAdapter -Physical | "
            "Where-Object { $_.InterfaceDescription -match 'Intel.*(Wi-Fi|Wireless|AX)' } | "
            "Restart-NetAdapter -Confirm:$false"
        )

    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=no_window,
        )
    except subprocess.TimeoutExpired:
        logger.error("wifi_optimizer: adapter restart timed out.")
        return {"ok": False, "error": "restart timed out"}
    except OSError as exc:
        logger.error("wifi_optimizer: adapter restart could not launch: %s", exc)
        return {"ok": False, "error": str(exc)}

    if result.returncode == 0:
        logger.info("wifi_optimizer: adapter restarted — driver re-read its config.")
        return {"ok": True, "error": ""}

    err = (result.stderr or result.stdout or "").strip() or f"exit code {result.returncode}"
    logger.error("wifi_optimizer: adapter restart failed: %s", err)
    return {"ok": False, "error": err}


def get_current_band() -> str:
    """
    Return the currently configured preferred band as a human-readable string.

    Returns ``"No Preference"``, ``"2.4GHz"``, ``"5GHz"``, ``"6GHz"``, or
    ``"5GHz + 6GHz"``. Defaults to ``"2.4GHz"`` if the value is absent or
    unrecognised.
    """
    adapter_key = get_wifi_adapter_key()
    if adapter_key is None:
        return "2.4GHz"
    roaming_val = _read_reg(adapter_key, "RoamingPreferredBandType")
    if roaming_val in _ROAMING_BAND_MAP:
        return _ROAMING_BAND_MAP[roaming_val]

    legacy_val = _read_reg(adapter_key, "PreferredBand")
    return _LEGACY_BAND_MAP.get(legacy_val, "2.4GHz")


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

    def restart_adapter(self, driver_desc: str | None = None) -> dict:
        return restart_adapter(driver_desc)

    def get_current_band(self) -> str:
        return get_current_band()

    def test_latency(self, host: str = "1.1.1.1") -> float:
        return test_latency(host)
