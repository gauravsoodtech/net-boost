"""
network_optimizer.py — TCP/registry network optimizer for NetBoost.

Applies Nagle-algorithm disabling (TcpAckFrequency, TCPNoDelay) and optional
TCP window-scaling tweaks by writing to per-interface GUID registry keys under
HKLM\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces.

Requires administrator privileges.
"""

import logging
import socket
import winreg

import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TCP_PARAMS_BASE = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"

# Registry value names written / restored by this optimizer.
_PER_IFACE_VALUES = ("TcpAckFrequency", "TCPNoDelay")
_GLOBAL_VALUES = ("Tcp1323Opts", "GlobalMaxTcpWindowSize")
_GLOBAL_KEY = r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters"


# ---------------------------------------------------------------------------
# Internal registry helpers
# ---------------------------------------------------------------------------

def _write_reg(key_path: str, value_name: str, value: int,
               value_type: int = winreg.REG_DWORD) -> None:
    """Write *value* to HKLM\\*key_path*\\*value_name*."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            key_path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.SetValueEx(key, value_name, 0, value_type, value)
        logger.info("Registry write: HKLM\\%s\\%s = %r", key_path, value_name, value)
    except OSError as exc:
        logger.error(
            "Failed to write HKLM\\%s\\%s: %s", key_path, value_name, exc
        )
        raise


def _read_reg(key_path: str, value_name: str):
    """
    Read a registry value from HKLM\\*key_path*.

    Returns a ``(value, type)`` tuple or ``None`` if the value does not exist.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            key_path,
            0,
            winreg.KEY_QUERY_VALUE,
        ) as key:
            return winreg.QueryValueEx(key, value_name)  # (value, type)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning(
            "Could not read HKLM\\%s\\%s: %s", key_path, value_name, exc
        )
        return None


def _delete_reg(key_path: str, value_name: str) -> None:
    """Delete *value_name* from HKLM\\*key_path*, silently ignoring absence."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            key_path,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, value_name)
        logger.info("Registry delete: HKLM\\%s\\%s", key_path, value_name)
    except FileNotFoundError:
        pass  # already gone — that's fine
    except OSError as exc:
        logger.warning(
            "Could not delete HKLM\\%s\\%s: %s", key_path, value_name, exc
        )


# ---------------------------------------------------------------------------
# GUID enumeration
# ---------------------------------------------------------------------------

def get_interface_guids() -> dict[str, str]:
    """
    Enumerate all GUID subkeys under TCP_PARAMS_BASE and match them against
    active psutil network adapters.

    Returns a mapping of ``{adapter_name: full_registry_subkey_path}``.
    """
    # Build a set of all known local IP addresses per adapter name.
    adapter_ips: dict[str, set[str]] = {}
    for adapter, addrs in psutil.net_if_addrs().items():
        ips: set[str] = set()
        for addr in addrs:
            if addr.family == socket.AF_INET and addr.address:
                ips.add(addr.address)
        if ips:
            adapter_ips[adapter] = ips

    result: dict[str, str] = {}

    try:
        base_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            TCP_PARAMS_BASE,
            0,
            winreg.KEY_READ,
        )
    except OSError as exc:
        logger.error("Cannot open TCP_PARAMS_BASE: %s", exc)
        return result

    with base_key:
        idx = 0
        while True:
            try:
                guid = winreg.EnumKey(base_key, idx)
            except OSError:
                break
            idx += 1

            subkey_path = f"{TCP_PARAMS_BASE}\\{guid}"

            # Read candidate IP addresses stored in the registry for this GUID.
            reg_ips: set[str] = set()
            for value_name in ("DhcpIPAddress", "IPAddress"):
                result_val = _read_reg(subkey_path, value_name)
                if result_val is None:
                    continue
                val, vtype = result_val
                if isinstance(val, str):
                    if val and val != "0.0.0.0":
                        reg_ips.add(val)
                elif isinstance(val, (list, tuple)):
                    for ip in val:
                        if ip and ip != "0.0.0.0":
                            reg_ips.add(ip)

            if not reg_ips:
                continue

            # Match against known adapter IPs.
            for adapter_name, ips in adapter_ips.items():
                if reg_ips & ips:
                    result[adapter_name] = subkey_path
                    logger.debug(
                        "Matched adapter '%s' -> GUID key '%s'",
                        adapter_name, subkey_path,
                    )
                    break

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply(settings: dict) -> dict:
    """
    Apply TCP optimizations according to *settings*.

    Writes per-interface registry values and optionally global TCP parameters.
    Returns a *backup* dict that can be passed to :func:`restore`.

    Settings keys consumed:
    - ``window_scaling`` (bool): if True, also write Tcp1323Opts and
      GlobalMaxTcpWindowSize to the global Parameters key.
    """
    backup: dict = {
        "interfaces": {},   # {adapter_name: {value_name: (value, type) | None}}
        "global": {},       # {value_name: (value, type) | None}
    }

    guids = get_interface_guids()
    if not guids:
        logger.warning("No matching interface GUIDs found; TCP optimisation skipped.")
        return backup

    for adapter_name, key_path in guids.items():
        iface_backup: dict = {}

        # --- Nagle / ack-frequency tweaks ---
        if settings.get("tcp_ack_freq"):
            iface_backup["TcpAckFrequency"] = _read_reg(key_path, "TcpAckFrequency")
            _write_reg(key_path, "TcpAckFrequency", 1)
        if settings.get("tcp_no_delay"):
            iface_backup["TCPNoDelay"] = _read_reg(key_path, "TCPNoDelay")
            _write_reg(key_path, "TCPNoDelay", 1)

        backup["interfaces"][adapter_name] = iface_backup

    # --- Optional: TCP window scaling (global key) ---
    if settings.get("window_scaling"):
        global_backup: dict = {}
        # Tcp1323Opts=1: window scaling only (bit 0).  Value 3 also enables
        # RFC 1323 timestamps (bit 1) which add 12 bytes overhead per packet
        # with no latency benefit when GlobalMaxTcpWindowSize is 65535.
        for value_name, new_val in (("Tcp1323Opts", 1), ("GlobalMaxTcpWindowSize", 65535)):
            global_backup[value_name] = _read_reg(_GLOBAL_KEY, value_name)
            _write_reg(_GLOBAL_KEY, value_name, new_val)
        backup["global"] = global_backup

    logger.info("TCP optimizations applied to %d interface(s).", len(guids))
    return backup


def restore(backup: dict) -> None:
    """
    Restore registry values from *backup* (as returned by :func:`apply`).

    Values that did not previously exist are deleted.
    """
    # Resolve GUIDs once for all adapters.
    guids = get_interface_guids()

    # Restore per-interface values.
    for adapter_name, iface_backup in backup.get("interfaces", {}).items():
        key_path = guids.get(adapter_name)
        if key_path is None:
            logger.warning(
                "Cannot restore adapter '%s': GUID not found.", adapter_name,
            )
            continue
        for value_name, original in iface_backup.items():
            _restore_value(key_path, value_name, original)

    # Restore global values.
    for value_name, original in backup.get("global", {}).items():
        _restore_value(_GLOBAL_KEY, value_name, original)

    logger.info("TCP registry values restored.")


def _restore_value(key_path: str, value_name: str, original) -> None:
    """Write *original* back, or delete the value if *original* is None."""
    if original is None:
        _delete_reg(key_path, value_name)
    elif isinstance(original, (tuple, list)) and len(original) >= 2:
        value, vtype = original[0], original[1]
        _write_reg(key_path, value_name, value, vtype)
    else:
        logger.warning(
            "Unexpected backup format for %s\\%s: %r — skipping",
            key_path, value_name, original,
        )


# ---------------------------------------------------------------------------
# NetworkOptimizer class — object-oriented wrapper used by the UI and tests
# ---------------------------------------------------------------------------

class NetworkOptimizer:
    """
    Object-oriented interface for TCP/registry network optimization.

    Wraps the module-level :func:`apply`, :func:`restore`, and
    :func:`get_interface_guids` functions for use from UI code, integration
    tests, or wherever an instance API is preferred.
    """

    def get_interface_guids(self) -> dict[str, str]:
        """Return ``{adapter_name: registry_subkey_path}`` for all matched interfaces."""
        return get_interface_guids()

    def apply(self, settings: dict) -> dict:
        """
        Apply TCP optimizations and return a backup dict.

        See module-level :func:`apply` for *settings* keys.
        """
        return apply(settings)

    def restore(self, backup: dict) -> None:
        """Restore registry values from *backup* (returned by :meth:`apply`)."""
        restore(backup)
