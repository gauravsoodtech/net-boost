"""
background_killer.py — Background process and Windows service killer for NetBoost.

Pauses or stops noisy background services (Windows Update, BITS, Windows Search,
OneDrive sync) and suspends bandwidth/CPU-heavy processes for the duration of a
gaming session.  All operations are best-effort: errors are logged but never
raised so that a partial failure does not block the rest of the teardown.

Requires administrator privileges for service operations.
"""

import logging
import time

import psutil
import win32service
import win32serviceutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Prefix for per-user OneDrive sync services (enumerated dynamically).
ONESYNC_PREFIX = "OneSyncSvc"

# Processes to *suspend* (not kill) — CPU/IO hogs.
PROCESSES_TO_SUSPEND = [
    "SearchIndexer.exe",
    # MsMpEng.exe (Windows Defender) removed — suspending it causes network
    # inspection interruptions and Windows health-check interference that
    # manifests as in-game latency spikes.
]

# Browser processes to deprioritize (lower scheduling priority).
PROCESSES_TO_DEPRIORITIZE = [
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
]

# Win32 priority class — BELOW_NORMAL
_BELOW_NORMAL_PRIORITY_CLASS = 0x4000


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------

def _get_service_state(name: str) -> int | None:
    """
    Return the current ``SERVICE_*`` state integer for *name*, or ``None`` if
    the service does not exist or cannot be queried.
    """
    try:
        status = win32serviceutil.QueryServiceStatus(name)
        return status[1]  # dwCurrentState
    except Exception as exc:
        logger.debug("background_killer: cannot query service '%s': %s", name, exc)
        return None


def _pause_or_stop_service(name: str) -> dict:
    """
    Try to PAUSE *name*; if the service does not accept pause controls, STOP it
    instead.

    Returns a dict::

        {
            "name":           str,
            "action":         "pause" | "stop" | "none",
            "previous_state": int,
        }
    """
    entry = {"name": name, "action": "none", "previous_state": -1}
    state = _get_service_state(name)

    if state is None:
        logger.debug("background_killer: service '%s' not found.", name)
        return entry

    entry["previous_state"] = state

    if state in (win32service.SERVICE_STOPPED, win32service.SERVICE_STOP_PENDING):
        logger.debug("background_killer: service '%s' already stopped.", name)
        return entry  # Nothing to do.

    # Try PAUSE first.
    try:
        win32serviceutil.PauseService(name)
        _wait_for_service_state(name, win32service.SERVICE_PAUSED, timeout=10)
        entry["action"] = "pause"
        logger.info("background_killer: service '%s' paused.", name)
        return entry
    except Exception as exc:
        logger.debug("background_killer: pause failed for '%s' (%s); trying stop.", name, exc)

    # Fall back to STOP.
    try:
        win32serviceutil.StopService(name)
        _wait_for_service_state(name, win32service.SERVICE_STOPPED, timeout=15)
        entry["action"] = "stop"
        logger.info("background_killer: service '%s' stopped.", name)
    except Exception as exc:
        logger.warning("background_killer: could not stop service '%s': %s", name, exc)

    return entry


def _resume_or_start_service(backup_entry: dict) -> None:
    """
    Reverse the action recorded in *backup_entry* (pause → continue,
    stop → start).
    """
    name   = backup_entry.get("name", "")
    action = backup_entry.get("action", "none")

    if action == "none":
        return

    if action == "pause":
        try:
            win32serviceutil.ContinueService(name)
            logger.info("background_killer: service '%s' resumed.", name)
        except Exception as exc:
            logger.warning("background_killer: could not resume service '%s': %s", name, exc)

    elif action == "stop":
        try:
            win32serviceutil.StartService(name)
            logger.info("background_killer: service '%s' started.", name)
        except Exception as exc:
            logger.warning("background_killer: could not start service '%s': %s", name, exc)


def _wait_for_service_state(name: str, desired_state: int, timeout: int = 10) -> None:
    """Poll until the service reaches *desired_state* or *timeout* seconds elapse."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = _get_service_state(name)
        if state == desired_state:
            return
        time.sleep(0.5)


def _find_onesync_services() -> list[str]:
    """
    Enumerate all installed services and return names that start with
    ``OneSyncSvc`` (per-user OneDrive sync service instances).
    """
    results: list[str] = []
    try:
        scm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
        try:
            services = win32service.EnumServicesStatus(
                scm,
                win32service.SERVICE_WIN32,
                win32service.SERVICE_STATE_ALL,
            )
            for svc_name, _, _ in services:
                if svc_name.startswith(ONESYNC_PREFIX):
                    results.append(svc_name)
        finally:
            win32service.CloseServiceHandle(scm)
    except Exception as exc:
        logger.warning("background_killer: cannot enumerate services: %s", exc)
    return results


# ---------------------------------------------------------------------------
# Process helpers
# ---------------------------------------------------------------------------

def suspend_process(pid: int) -> None:
    """Suspend (freeze) process *pid* via psutil."""
    try:
        psutil.Process(pid).suspend()
        logger.info("background_killer: PID %d suspended.", pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        logger.debug("background_killer: cannot suspend PID %d: %s", pid, exc)
    except Exception as exc:
        logger.warning("background_killer: suspend error for PID %d: %s", pid, exc)


def resume_process(pid: int) -> None:
    """Resume process *pid* via psutil."""
    try:
        psutil.Process(pid).resume()
        logger.info("background_killer: PID %d resumed.", pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        logger.debug("background_killer: cannot resume PID %d: %s", pid, exc)
    except Exception as exc:
        logger.warning("background_killer: resume error for PID %d: %s", pid, exc)


def _deprioritize_process(pid: int, name: str) -> None:
    """Lower the scheduling priority of *pid* to BELOW_NORMAL."""
    try:
        import win32api
        import win32con
        import win32process
        handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, pid)
        try:
            win32process.SetPriorityClass(handle, _BELOW_NORMAL_PRIORITY_CLASS)
            logger.info("background_killer: '%s' (PID %d) deprioritized.", name, pid)
        finally:
            win32api.CloseHandle(handle)
    except Exception as exc:
        logger.debug("background_killer: cannot deprioritize '%s' PID %d: %s", name, pid, exc)


def _find_pids_by_name(exe_name: str) -> list[int]:
    """Return a list of PIDs for all processes whose name matches *exe_name*."""
    results: list[int] = []
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if (proc.info["name"] or "").lower() == exe_name.lower():
                results.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply(settings: dict) -> dict:
    """
    Pause/stop services and suspend processes according to *settings*.

    Settings keys consumed (all bool):
    - ``pause_windows_update``  — pause/stop Windows Update (wuauserv)
    - ``pause_bits``     — pause/stop BITS
    - ``pause_onedrive`` — pause/stop OneSyncSvc_* services + suspend OneDrive.exe

    In addition, SearchIndexer.exe is always suspended and browsers are
    deprioritized.

    Returns a *backup* dict suitable for :func:`restore`.
    """
    backup: dict = {
        "services_backup": [],
        "suspended_pids":  [],
    }

    # --- Windows Update ---
    if settings.get("pause_windows_update"):
        entry = _pause_or_stop_service("wuauserv")
        backup["services_backup"].append(entry)

    # --- BITS ---
    if settings.get("pause_bits"):
        entry = _pause_or_stop_service("BITS")
        backup["services_backup"].append(entry)

    # --- OneDrive sync service(s) ---
    if settings.get("pause_onedrive"):
        for svc_name in _find_onesync_services():
            entry = _pause_or_stop_service(svc_name)
            backup["services_backup"].append(entry)

        # Also suspend OneDrive.exe process(es).
        for pid in _find_pids_by_name("OneDrive.exe"):
            suspend_process(pid)
            backup["suspended_pids"].append(pid)

    # --- Windows Telemetry (DiagTrack) ---
    if settings.get("pause_telemetry"):
        entry = _pause_or_stop_service("DiagTrack")
        backup["services_backup"].append(entry)

    # --- Always: suspend background CPU/IO hogs ---
    for exe_name in PROCESSES_TO_SUSPEND:
        for pid in _find_pids_by_name(exe_name):
            suspend_process(pid)
            backup["suspended_pids"].append(pid)

    # --- Deprioritize browsers ---
    for exe_name in PROCESSES_TO_DEPRIORITIZE:
        for pid in _find_pids_by_name(exe_name):
            _deprioritize_process(pid, exe_name)

    logger.info(
        "background_killer: apply() complete — %d service(s) handled, %d PID(s) suspended.",
        len(backup["services_backup"]),
        len(backup["suspended_pids"]),
    )
    return backup


def restore(backup: dict) -> None:
    """
    Restore services and resume processes from *backup*.

    Every operation is individually try/except guarded.
    """
    # Resume suspended processes first so they can pick up work again.
    for pid in backup.get("suspended_pids", []):
        try:
            resume_process(pid)
        except Exception as exc:
            logger.warning("background_killer: restore resume PID %d: %s", pid, exc)

    # Restore services.
    for entry in backup.get("services_backup", []):
        try:
            _resume_or_start_service(entry)
        except Exception as exc:
            logger.warning(
                "background_killer: restore service '%s': %s",
                entry.get("name", "?"), exc,
            )

    logger.info("background_killer: restore() complete.")


# ---------------------------------------------------------------------------
# Compat shim — called by state_guard.restore_all
# ---------------------------------------------------------------------------

def resume_service(name: str) -> None:
    """
    Resume or start a single service by *name*.

    This is a convenience wrapper used by :mod:`core.state_guard` when
    replaying a crash-recovery sequence from the persisted service list.
    """
    entry = {"name": name, "action": "stop", "previous_state": -1}
    # We recorded only the name; default to "stop" so that _resume_or_start_service
    # calls StartService, which is safe whether the service was paused or stopped.
    _resume_or_start_service(entry)


# ---------------------------------------------------------------------------
# BackgroundKiller class — object-oriented wrapper used by the UI
# ---------------------------------------------------------------------------

class BackgroundKiller:
    """Object-oriented interface for background process/service management."""

    def apply(self, settings: dict) -> dict:
        return apply(settings)

    def restore(self, backup: dict) -> None:
        restore(backup)

    def suspend_process(self, pid: int) -> None:
        suspend_process(pid)

    def resume_process(self, pid: int) -> None:
        resume_process(pid)

    def resume_service(self, name: str) -> None:
        resume_service(name)
