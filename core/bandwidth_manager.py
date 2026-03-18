"""
bandwidth_manager.py — QoS DSCP policy and process-priority manager for NetBoost.

Creates per-application QoS policies via the Windows registry (Group Policy
QoS) and adjusts process scheduling priority through pywin32.

Requires administrator privileges.
"""

import logging
import winreg

import psutil
import win32api
import win32con
import win32process

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DSCP_POLICY_BASE = r"SOFTWARE\Policies\Microsoft\Windows\QoS"

# Priority class identifiers (subset of Win32 values).
_PRIORITY_NAMES: dict[int, str] = {
    0x0020: "NORMAL",
    0x0040: "IDLE",
    0x0080: "HIGH",
    0x0100: "REALTIME",
    0x4000: "BELOW_NORMAL",
    0x8000: "ABOVE_NORMAL",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _open_process_for_priority(pid: int):
    """Return a Win32 handle to *pid* with PROCESS_ALL_ACCESS."""
    return win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, pid)


# ---------------------------------------------------------------------------
# DSCP policy registry management
# ---------------------------------------------------------------------------

def apply_dscp_policy(
    policy_name: str,
    app_path: str,
    dscp_value: int = 46,
) -> bool:
    """
    Write a QoS DSCP policy under HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\QoS.

    Parameters
    ----------
    policy_name:
        Unique name for this policy (used as the registry subkey).
    app_path:
        Full path to the application executable (e.g. ``C:\\...\\game.exe``).
    dscp_value:
        DSCP value to tag outgoing packets with.  46 = Expedited Forwarding
        (highest-priority QoS class in enterprise / home routers that honour
        DSCP).

    Returns ``True`` on success, ``False`` on failure.
    """
    subkey = f"{DSCP_POLICY_BASE}\\{policy_name}"
    policy_values: list[tuple[str, int, object]] = [
        ("Version",      winreg.REG_SZ,    "1.0"),
        ("Application",  winreg.REG_SZ,    app_path),
        ("Protocol",     winreg.REG_SZ,    "*"),
        ("LocalPort",    winreg.REG_SZ,    "*"),
        ("RemotePort",   winreg.REG_SZ,    "*"),
        ("LocalIP",      winreg.REG_SZ,    "*"),
        ("RemoteIP",     winreg.REG_SZ,    "*"),
        ("DSCPValue",    winreg.REG_SZ,    str(dscp_value)),
        ("ThrottleRate", winreg.REG_SZ,    "-1"),
    ]

    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_LOCAL_MACHINE,
            subkey,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            for name, vtype, value in policy_values:
                winreg.SetValueEx(key, name, 0, vtype, value)
        logger.info(
            "bandwidth_manager: DSCP policy '%s' created (DSCP=%d, app=%s).",
            policy_name, dscp_value, app_path,
        )
        return True
    except OSError as exc:
        logger.error("bandwidth_manager: failed to create DSCP policy '%s': %s", policy_name, exc)
        return False


def remove_dscp_policy(policy_name: str) -> None:
    """
    Delete the QoS DSCP policy registry key for *policy_name*.

    Silently ignores absence.
    """
    subkey = f"{DSCP_POLICY_BASE}\\{policy_name}"
    try:
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, subkey)
        logger.info("bandwidth_manager: DSCP policy '%s' removed.", policy_name)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning(
            "bandwidth_manager: could not remove DSCP policy '%s': %s", policy_name, exc
        )


# ---------------------------------------------------------------------------
# Process priority management
# ---------------------------------------------------------------------------

def set_process_priority(pid: int, priority_class: int) -> None:
    """Set the priority class of process *pid* to *priority_class*."""
    handle = _open_process_for_priority(pid)
    try:
        win32process.SetPriorityClass(handle, priority_class)
        label = _PRIORITY_NAMES.get(priority_class, hex(priority_class))
        logger.info("bandwidth_manager: PID %d priority set to %s.", pid, label)
    finally:
        win32api.CloseHandle(handle)


def get_process_priority(pid: int) -> int:
    """Return the current priority class integer for process *pid*."""
    handle = _open_process_for_priority(pid)
    try:
        return win32process.GetPriorityClass(handle)
    finally:
        win32api.CloseHandle(handle)


# ---------------------------------------------------------------------------
# Process listing
# ---------------------------------------------------------------------------

def get_running_processes() -> list[dict]:
    """
    Return a list of dicts for all user-space processes.

    Each dict has keys: ``pid``, ``name``, ``cpu_pct``, ``mem_mb``,
    ``priority``.  System processes that cannot be queried are skipped
    silently.
    """
    # Prime CPU percent counters with a non-blocking call.
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
        pass

    import time
    time.sleep(0.1)  # brief interval so cpu_percent is meaningful

    results: list[dict] = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
        try:
            info = proc.as_dict(attrs=["pid", "name", "cpu_percent", "memory_info"])
            pid  = info["pid"]
            name = info["name"] or ""

            # Skip idle / System pseudo-processes.
            if pid < 4 or name.lower() in ("system", "idle", ""):
                continue

            mem_mb = (info["memory_info"].rss // (1024 * 1024)) if info["memory_info"] else 0

            try:
                priority = get_process_priority(pid)
            except Exception:
                priority = win32con.NORMAL_PRIORITY_CLASS

            results.append({
                "pid":      pid,
                "name":     name,
                "cpu_pct":  round(info["cpu_percent"] or 0.0, 1),
                "mem_mb":   mem_mb,
                "priority": priority,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception as exc:
            logger.debug("bandwidth_manager: skipping process: %s", exc)

    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply(game_path: str, game_pid: int, settings: dict) -> dict:
    """
    Apply bandwidth / QoS optimizations for a game.

    Settings keys consumed:
    - ``game_priority`` (bool) — set game process to HIGH priority and apply
      DSCP EF policy.

    Returns a *backup* dict suitable for :func:`restore`.
    """
    backup: dict = {
        "dscp_policies": [],
        "pid":           game_pid,
        "prev_priority": None,
    }

    if settings.get("game_priority"):
        # DSCP policy for the game executable.
        policy_name = f"NetBoost_{_sanitise_name(game_path)}"
        if apply_dscp_policy(policy_name, game_path, dscp_value=46):
            backup["dscp_policies"].append(policy_name)

        # Raise process priority.
        try:
            prev_prio = get_process_priority(game_pid)
            set_process_priority(game_pid, win32con.HIGH_PRIORITY_CLASS)
            backup["prev_priority"] = prev_prio
        except Exception as exc:
            logger.warning("bandwidth_manager: priority change failed: %s", exc)

    logger.info("bandwidth_manager: apply() complete.")
    return backup


def restore(backup: dict) -> None:
    """
    Restore state from *backup* (as returned by :func:`apply`).

    Removes DSCP policies and restores the process priority.
    """
    for policy_name in backup.get("dscp_policies", []):
        remove_dscp_policy(policy_name)

    pid      = backup.get("pid")
    prev_pri = backup.get("prev_priority")
    if pid and prev_pri is not None:
        try:
            set_process_priority(pid, prev_pri)
        except Exception as exc:
            logger.warning(
                "bandwidth_manager: could not restore priority for PID %d: %s", pid, exc
            )

    logger.info("bandwidth_manager: restore() complete.")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _sanitise_name(path: str) -> str:
    """Return a registry-safe identifier derived from a file path."""
    import os
    import re
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[^A-Za-z0-9_\-]", "_", stem)[:64]


# ---------------------------------------------------------------------------
# Compat shim — called by state_guard.restore_all
# ---------------------------------------------------------------------------

def remove_policy(policy_name: str) -> None:
    """
    Alias for :func:`remove_dscp_policy`.

    Called by :mod:`core.state_guard` when replaying a crash-recovery sequence
    from the persisted QoS policy list.
    """
    remove_dscp_policy(policy_name)


# ---------------------------------------------------------------------------
# BandwidthManager class — object-oriented wrapper used by the UI
# ---------------------------------------------------------------------------

class BandwidthManager:
    """Object-oriented interface for bandwidth/QoS management."""

    def apply_dscp_policy(self, policy_name: str, app_path: str, dscp_value: int = 46) -> bool:
        return apply_dscp_policy(policy_name, app_path, dscp_value)

    def remove_dscp_policy(self, policy_name: str) -> None:
        remove_dscp_policy(policy_name)

    def set_process_priority(self, pid: int, priority_class: int) -> None:
        set_process_priority(pid, priority_class)

    def get_process_priority(self, pid: int) -> int:
        return get_process_priority(pid)

    def get_running_processes(self) -> list[dict]:
        return get_running_processes()

    def apply(self, game_path: str, game_pid: int, settings: dict) -> dict:
        return apply(game_path, game_pid, settings)

    def restore(self, backup: dict) -> None:
        restore(backup)

    def remove_policy(self, policy_name: str) -> None:
        remove_dscp_policy(policy_name)
