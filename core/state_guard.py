"""
state_guard.py — Crash-safe persistent state manager for NetBoost.

Stores optimizer state to %APPDATA%\\NetBoost\\state.json so that if the
application crashes mid-optimisation the next launch can detect the orphaned
state and automatically restore the system to a clean baseline.
"""

import json
import logging
import os
import tempfile

import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATE_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "NetBoost")
_STATE_FILE = os.path.join(_STATE_DIR, "state.json")

_EMPTY_STATE: dict = {
    "pid": None,
    "dns_backup": {},
    "tcp_backup": {},
    "paused_services": [],
    "suspended_pids": [],
    "qos_policies": [],
    "wifi_backup": {},
    "nvidia_backup": {},
    "fps_backup": {},
}


def _ensure_dir() -> None:
    os.makedirs(_STATE_DIR, exist_ok=True)


def _atomic_write(path: str, data: dict) -> None:
    """Write *data* to *path* atomically using a temp file + os.replace."""
    _ensure_dir()
    dir_name = os.path.dirname(path)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        # Clean up the temp file if something went wrong.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_state(state_dict: dict) -> None:
    """Persist *state_dict* to disk atomically."""
    _atomic_write(_STATE_FILE, state_dict)
    logger.debug("State saved to %s", _STATE_FILE)


def load_state() -> dict:
    """
    Load state from disk.

    Returns a fresh empty state dict if the file does not exist or is corrupt.
    """
    if not os.path.isfile(_STATE_FILE):
        return dict(_EMPTY_STATE)
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Ensure all expected keys are present (forward-compat).
        merged = dict(_EMPTY_STATE)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load state file (%s); using empty state.", exc)
        return dict(_EMPTY_STATE)


def clear() -> None:
    """Delete the persisted state file."""
    try:
        os.remove(_STATE_FILE)
        logger.info("State file cleared.")
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.error("Failed to clear state file: %s", exc)


def check_and_heal() -> bool:
    """
    Check whether the previous NetBoost process is still alive.

    If the recorded PID is dead (crash / force-kill) this method calls
    :func:`restore_all` to undo any lingering optimisations and returns
    ``True``.  Returns ``False`` when no healing was needed.
    """
    state = load_state()
    prev_pid = state.get("pid")

    if prev_pid is None:
        logger.debug("No previous PID in state; nothing to heal.")
        return False

    if prev_pid == os.getpid():
        # Same process — nothing to heal.
        return False

    if psutil.pid_exists(prev_pid):
        logger.debug("Previous NetBoost PID %d is still running; no heal needed.", prev_pid)
        return False

    logger.warning(
        "Previous NetBoost PID %d is dead; orphaned optimisations detected — healing …",
        prev_pid,
    )
    restore_all(state=state)
    return True


def restore_all(state: dict | None = None) -> None:
    """
    Attempt to undo all recorded optimisations stored in *state*.

    This is intentionally best-effort: individual restore helpers are wrapped
    in try/except so that a failure in one step does not prevent the others
    from running.

    Concrete restoration logic lives in the individual optimizer modules;
    this function provides a central orchestration point and imports lazily to
    avoid circular imports.
    """
    if state is None:
        state = load_state()

    logger.info("restore_all: beginning system restore …")

    # DNS restore
    dns_backup = state.get("dns_backup") or {}
    if dns_backup:
        try:
            from core import dns_optimizer  # type: ignore[import]
            dns_optimizer.restore(dns_backup)
            logger.info("restore_all: DNS restored.")
        except Exception as exc:
            logger.error("restore_all: DNS restore failed: %s", exc)

    # TCP restore
    tcp_backup = state.get("tcp_backup") or {}
    if tcp_backup:
        try:
            from core import tcp_optimizer  # type: ignore[import]
            tcp_optimizer.restore(tcp_backup)
            logger.info("restore_all: TCP settings restored.")
        except Exception as exc:
            logger.error("restore_all: TCP restore failed: %s", exc)

    # Resume paused Windows services
    paused_services: list = state.get("paused_services") or []
    if paused_services:
        try:
            from core import background_killer  # type: ignore[import]
            for svc in paused_services:
                background_killer.resume_service(svc)
            logger.info("restore_all: %d service(s) resumed.", len(paused_services))
        except Exception as exc:
            logger.error("restore_all: Service resume failed: %s", exc)

    # Resume suspended processes
    suspended_pids: list = state.get("suspended_pids") or []
    if suspended_pids:
        for pid in suspended_pids:
            try:
                proc = psutil.Process(pid)
                proc.resume()
                logger.info("restore_all: Resumed PID %d.", pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                logger.warning("restore_all: Could not resume PID %d: %s", pid, exc)

    # Remove QoS policies
    qos_policies: list = state.get("qos_policies") or []
    if qos_policies:
        try:
            from core import bandwidth_manager  # type: ignore[import]
            for policy in qos_policies:
                bandwidth_manager.remove_policy(policy)
            logger.info("restore_all: %d QoS policy(ies) removed.", len(qos_policies))
        except Exception as exc:
            logger.error("restore_all: QoS restore failed: %s", exc)

    # Wi-Fi restore
    wifi_backup = state.get("wifi_backup") or {}
    if wifi_backup:
        try:
            from core import wifi_optimizer  # type: ignore[import]
            wifi_optimizer.restore(wifi_backup)
            logger.info("restore_all: Wi-Fi settings restored.")
        except Exception as exc:
            logger.error("restore_all: Wi-Fi restore failed: %s", exc)

    # NVIDIA restore
    nvidia_backup = state.get("nvidia_backup") or {}
    if nvidia_backup:
        try:
            from core import nvidia_optimizer  # type: ignore[import]
            nvidia_optimizer.restore(nvidia_backup)
            logger.info("restore_all: NVIDIA settings restored.")
        except Exception as exc:
            logger.error("restore_all: NVIDIA restore failed: %s", exc)

    # FPS / system tweaks restore
    fps_backup = state.get("fps_backup") or {}
    if fps_backup:
        try:
            from core import fps_booster  # type: ignore[import]
            fps_booster.restore(fps_backup)
            logger.info("restore_all: FPS tweaks restored.")
        except Exception as exc:
            logger.error("restore_all: FPS restore failed: %s", exc)

    clear()
    logger.info("restore_all: complete.")


# ---------------------------------------------------------------------------
# Mutation helpers — each records a sub-section of the state and re-saves.
# ---------------------------------------------------------------------------

def _mutate(key: str, value) -> None:
    """Load current state, update *key* with *value*, and save."""
    state = load_state()
    state[key] = value
    state["pid"] = os.getpid()
    save_state(state)


def record_dns_backup(backup: dict) -> None:
    """Store the pre-optimisation DNS configuration for later restoration."""
    _mutate("dns_backup", backup)


def record_tcp_backup(backup: dict) -> None:
    """Store the pre-optimisation TCP registry values."""
    _mutate("tcp_backup", backup)


def record_wifi_backup(backup: dict) -> None:
    """Store the pre-optimisation Wi-Fi adapter settings."""
    _mutate("wifi_backup", backup)


def record_nvidia_backup(backup: dict) -> None:
    """Store the pre-optimisation NVIDIA driver settings."""
    _mutate("nvidia_backup", backup)


def record_fps_backup(backup: dict) -> None:
    """Store the pre-optimisation FPS/system tweak values."""
    _mutate("fps_backup", backup)


def add_paused_service(name: str) -> None:
    """Register a Windows service that has been paused by NetBoost."""
    state = load_state()
    services: list = state.get("paused_services") or []
    if name not in services:
        services.append(name)
    state["paused_services"] = services
    state["pid"] = os.getpid()
    save_state(state)


def remove_paused_service(name: str) -> None:
    """Deregister a Windows service after it has been successfully resumed."""
    state = load_state()
    services: list = state.get("paused_services") or []
    state["paused_services"] = [s for s in services if s != name]
    save_state(state)


def add_suspended_pid(pid: int) -> None:
    """Register a process PID that has been suspended by NetBoost."""
    state = load_state()
    pids: list = state.get("suspended_pids") or []
    if pid not in pids:
        pids.append(pid)
    state["suspended_pids"] = pids
    state["pid"] = os.getpid()
    save_state(state)


def remove_suspended_pid(pid: int) -> None:
    """Deregister a process PID after it has been successfully resumed."""
    state = load_state()
    pids: list = state.get("suspended_pids") or []
    state["suspended_pids"] = [p for p in pids if p != pid]
    save_state(state)


def add_qos_policy(name: str) -> None:
    """Register a QoS policy that has been created by NetBoost."""
    state = load_state()
    policies: list = state.get("qos_policies") or []
    if name not in policies:
        policies.append(name)
    state["qos_policies"] = policies
    state["pid"] = os.getpid()
    save_state(state)


def get_state() -> dict:
    """Return the current persisted state dict (read-only snapshot)."""
    return load_state()


# ---------------------------------------------------------------------------
# Class wrapper (used by main.py and main_window.py)
# ---------------------------------------------------------------------------

class StateGuard:
    """Thin class wrapper around the module-level state functions."""

    def save_state(self, state_dict: dict) -> None:
        save_state(state_dict)

    def load_state(self) -> dict:
        return load_state()

    def check_and_heal(self) -> bool:
        return check_and_heal()

    def restore_all(self) -> None:
        restore_all()

    def clear(self) -> None:
        clear()

    def get_state(self) -> dict:
        return get_state()

    def record_dns_backup(self, backup: dict) -> None:
        record_dns_backup(backup)

    def record_tcp_backup(self, backup: dict) -> None:
        record_tcp_backup(backup)

    def record_wifi_backup(self, backup: dict) -> None:
        record_wifi_backup(backup)

    def record_nvidia_backup(self, backup: dict) -> None:
        record_nvidia_backup(backup)

    def record_fps_backup(self, backup: dict) -> None:
        record_fps_backup(backup)

    def add_paused_service(self, name: str) -> None:
        add_paused_service(name)

    def remove_paused_service(self, name: str) -> None:
        remove_paused_service(name)

    def add_suspended_pid(self, pid: int) -> None:
        add_suspended_pid(pid)

    def remove_suspended_pid(self, pid: int) -> None:
        remove_suspended_pid(pid)

    def add_qos_policy(self, name: str) -> None:
        add_qos_policy(name)
