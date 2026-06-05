"""
state_guard.py — Crash-safe persistent state manager for NetBoost.

Stores optimizer state to %APPDATA%\\NetBoost\\state.json so that if the
application crashes mid-optimisation the next launch can detect the orphaned
state and automatically restore the system to a clean baseline.
"""

import copy
import json
import logging
import os
import tempfile
import time

import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATE_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "NetBoost")
_STATE_FILE = os.path.join(_STATE_DIR, "state.json")

# Dict-replacing backup keys whose mutation can produce a branch-on-apply.
_BACKUP_DICT_KEYS = (
    "dns_backup",
    "tcp_backup",
    "wifi_backup",
    "nvidia_backup",
    "fps_backup",
    "msi_backup",
    "ndu_backup",
    "throttling_backup",
)
# Cumulative list keys mirrored into every history entry.
_BACKUP_LIST_KEYS = ("paused_services", "suspended_pids", "qos_policies")
# Cap history at this many entries — drops oldest when exceeded.
_BACKUP_HISTORY_CAP = 5

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
    "msi_backup": {},
    "ndu_backup": {},
    "throttling_backup": {},
    "backup_history": [],
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

    Legacy `state.json` files written before backup_history was introduced
    are migrated on read by wrapping their flat backup snapshot as a single
    history entry, so crash recovery still finds something to replay.
    """
    if not os.path.isfile(_STATE_FILE):
        return copy.deepcopy(_EMPTY_STATE)
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        merged = copy.deepcopy(_EMPTY_STATE)
        merged.update(data)

        if not merged.get("backup_history") and _has_recoverable_state(merged):
            merged["backup_history"] = [_snapshot_from_flat(merged, ts=0.0)]

        return merged
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load state file (%s); using empty state.", exc)
        return copy.deepcopy(_EMPTY_STATE)


def _has_recoverable_state(state: dict) -> bool:
    """Return True if any flat backup key is non-empty — used by migration shim."""
    if any(state.get(k) for k in _BACKUP_DICT_KEYS):
        return True
    if any(state.get(k) for k in _BACKUP_LIST_KEYS):
        return True
    return False


def _snapshot_from_flat(state: dict, ts: float) -> dict:
    """Build a backup_history entry from the flat top-level keys in *state*."""
    snapshot = {"ts": ts}
    for key in _BACKUP_DICT_KEYS:
        snapshot[key] = dict(state.get(key) or {})
    for key in _BACKUP_LIST_KEYS:
        snapshot[key] = list(state.get(key) or [])
    return snapshot


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


def _wifi_backup_requires_restart(backup: dict) -> bool:
    """Return True when a restored Wi-Fi backup needs a miniport reset."""
    return bool(
        backup
        and backup.get("_adapter_found", True)
        and backup.get("_requires_restart")
    )


def _restore_entry(entry: dict) -> dict:
    """
    Replay a single backup_history snapshot.  Best-effort: each section is
    individually try/except guarded so a failure in one does not block the
    others.
    """
    result = {"wifi_restart_required": False, "wifi_driver_desc": None}

    dns_backup = entry.get("dns_backup") or {}
    if dns_backup:
        try:
            from core import dns_optimizer  # type: ignore[import]
            dns_optimizer.restore(dns_backup)
            logger.info("restore_all: DNS restored.")
        except Exception as exc:
            logger.error("restore_all: DNS restore failed: %s", exc)

    tcp_backup = entry.get("tcp_backup") or {}
    if tcp_backup:
        try:
            from core import tcp_optimizer  # type: ignore[import]
            tcp_optimizer.restore(tcp_backup)
            logger.info("restore_all: TCP settings restored.")
        except Exception as exc:
            logger.error("restore_all: TCP restore failed: %s", exc)

    paused_services: list = entry.get("paused_services") or []
    if paused_services:
        try:
            from core import background_killer  # type: ignore[import]
            for svc in paused_services:
                background_killer.resume_service(svc)
            logger.info("restore_all: %d service(s) resumed.", len(paused_services))
        except Exception as exc:
            logger.error("restore_all: Service resume failed: %s", exc)

    suspended_pids: list = entry.get("suspended_pids") or []
    for pid in suspended_pids:
        try:
            proc = psutil.Process(pid)
            proc.resume()
            logger.info("restore_all: Resumed PID %d.", pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            logger.warning("restore_all: Could not resume PID %d: %s", pid, exc)

    qos_policies: list = entry.get("qos_policies") or []
    if qos_policies:
        try:
            from core import bandwidth_manager  # type: ignore[import]
            for policy in qos_policies:
                bandwidth_manager.remove_policy(policy)
            logger.info("restore_all: %d QoS policy(ies) removed.", len(qos_policies))
        except Exception as exc:
            logger.error("restore_all: QoS restore failed: %s", exc)

    wifi_backup = entry.get("wifi_backup") or {}
    if wifi_backup:
        try:
            from core import wifi_optimizer  # type: ignore[import]
            wifi_optimizer.restore(dict(wifi_backup))
            if _wifi_backup_requires_restart(wifi_backup):
                result["wifi_restart_required"] = True
                result["wifi_driver_desc"] = wifi_backup.get("_driver_desc")
            logger.info("restore_all: Wi-Fi settings restored.")
        except Exception as exc:
            logger.error("restore_all: Wi-Fi restore failed: %s", exc)

    nvidia_backup = entry.get("nvidia_backup") or {}
    if nvidia_backup:
        try:
            from core import nvidia_optimizer  # type: ignore[import]
            nvidia_optimizer.restore(nvidia_backup)
            logger.info("restore_all: NVIDIA settings restored.")
        except Exception as exc:
            logger.error("restore_all: NVIDIA restore failed: %s", exc)

    fps_backup = entry.get("fps_backup") or {}
    if fps_backup:
        try:
            from core import fps_booster  # type: ignore[import]
            fps_booster.restore(fps_backup)
            logger.info("restore_all: FPS tweaks restored.")
        except Exception as exc:
            logger.error("restore_all: FPS restore failed: %s", exc)

    msi_backup = entry.get("msi_backup") or {}
    if msi_backup:
        try:
            from core import system_tweaks  # type: ignore[import]
            system_tweaks.restore_msi_mode(msi_backup)
            logger.info("restore_all: MSI Mode restored.")
        except Exception as exc:
            logger.error("restore_all: MSI restore failed: %s", exc)

    ndu_backup = entry.get("ndu_backup") or {}
    if ndu_backup:
        try:
            from core import system_tweaks  # type: ignore[import]
            system_tweaks.restore_ndu_service(ndu_backup)
            logger.info("restore_all: NDU service restored.")
        except Exception as exc:
            logger.error("restore_all: NDU restore failed: %s", exc)

    throttling_backup = entry.get("throttling_backup") or {}
    if throttling_backup:
        try:
            from core import system_tweaks  # type: ignore[import]
            system_tweaks.restore_network_throttling(throttling_backup)
            logger.info("restore_all: Network throttling restored.")
        except Exception as exc:
            logger.error("restore_all: Throttling restore failed: %s", exc)

    return result


def restore_all(state: dict | None = None) -> None:
    """
    Walk backup_history newest → oldest and replay every recorded snapshot.

    Each per-section restore is wrapped in try/except so a single failure
    cannot block the rest.  Restoring the same service or PID across multiple
    entries is safe — resume is idempotent and missing services/pids are
    swallowed by the per-section restore code.

    The persisted state file is cleared after the walk completes.
    """
    if state is None:
        state = load_state()

    history = list(state.get("backup_history") or [])
    if not history:
        logger.info("restore_all: no backup_history; nothing to restore.")
        clear()
        return

    logger.info("restore_all: beginning system restore over %d snapshot(s) …", len(history))
    wifi_restart_required = False
    wifi_driver_desc = None
    for entry in reversed(history):
        result = _restore_entry(entry)
        if result.get("wifi_restart_required"):
            wifi_restart_required = True
            wifi_driver_desc = result.get("wifi_driver_desc") or wifi_driver_desc

    if wifi_restart_required:
        try:
            from core import wifi_optimizer  # type: ignore[import]
            restart = wifi_optimizer.restart_adapter(wifi_driver_desc)
            if restart.get("ok"):
                logger.info("restore_all: Wi-Fi adapter restarted after restore.")
            else:
                logger.warning(
                    "restore_all: Wi-Fi adapter restart after restore failed: %s",
                    restart.get("error", ""),
                )
        except Exception as exc:
            logger.error("restore_all: Wi-Fi adapter restart failed: %s", exc)

    clear()
    logger.info("restore_all: complete.")


# ---------------------------------------------------------------------------
# Mutation helpers — each records a sub-section of the state and re-saves.
# ---------------------------------------------------------------------------

def _mutate(key: str, value) -> None:
    """
    Load current state, update *key* with *value*, and save.

    For cumulative list keys (paused_services / suspended_pids / qos_policies),
    also mirror the updated list into the latest backup_history entry so that
    restore_all sees the same data when walking history.
    """
    state = load_state()
    state[key] = value
    state["pid"] = os.getpid()

    if key in _BACKUP_LIST_KEYS:
        history = state.get("backup_history") or []
        if not history:
            history = [_snapshot_from_flat(state, ts=time.time())]
            state["backup_history"] = history
        else:
            history[-1][key] = list(value) if isinstance(value, list) else value

    save_state(state)


def _mutate_backup_dict(key: str, value: dict) -> None:
    """
    Branch-aware mutator for the dict-replacing backup keys.

    A new backup_history entry is appended only when the previous mirrored
    value for *key* is non-empty AND different from *value* — that is exactly
    the case where overwriting in place would lose a real prior backup.
    Otherwise the latest entry is updated in place.  History is capped at
    `_BACKUP_HISTORY_CAP` entries, dropping the oldest.
    """
    state = load_state()
    state["pid"] = os.getpid()

    history: list = state.setdefault("backup_history", [])

    if not history:
        # First record under this PID — seed an entry from the current flat keys
        # so any pre-existing list state (paused_services, etc.) is captured.
        seed = _snapshot_from_flat(state, ts=time.time())
        seed[key] = dict(value)
        history.append(seed)
    else:
        latest = history[-1]
        prev_value = latest.get(key) or {}
        if prev_value and prev_value != value:
            new_entry = {k: (dict(v) if isinstance(v, dict) else list(v))
                         for k, v in latest.items() if k != "ts"}
            new_entry["ts"] = time.time()
            new_entry[key] = dict(value)
            history.append(new_entry)
        else:
            latest[key] = dict(value)
            latest["ts"] = time.time()

    if len(history) > _BACKUP_HISTORY_CAP:
        del history[: len(history) - _BACKUP_HISTORY_CAP]

    state[key] = value  # mirror to flat top-level for backwards compatibility
    save_state(state)


def record_dns_backup(backup: dict) -> None:
    """Store the pre-optimisation DNS configuration for later restoration."""
    _mutate_backup_dict("dns_backup", backup)


def record_tcp_backup(backup: dict) -> None:
    """Store the pre-optimisation TCP registry values."""
    _mutate_backup_dict("tcp_backup", backup)


def record_wifi_backup(backup: dict) -> None:
    """Store the pre-optimisation Wi-Fi adapter settings."""
    _mutate_backup_dict("wifi_backup", backup)


def record_nvidia_backup(backup: dict) -> None:
    """Store the pre-optimisation NVIDIA driver settings."""
    _mutate_backup_dict("nvidia_backup", backup)


def record_fps_backup(backup: dict) -> None:
    """Store the pre-optimisation FPS/system tweak values."""
    _mutate_backup_dict("fps_backup", backup)


def record_msi_backup(backup: dict) -> None:
    """Store the pre-MSI-Mode per-device MSISupported values."""
    _mutate_backup_dict("msi_backup", backup)


def record_ndu_backup(backup: dict) -> None:
    """Store the pre-disable NDU service Start value."""
    _mutate_backup_dict("ndu_backup", backup)


def record_throttling_backup(backup: dict) -> None:
    """Store the pre-disable NetworkThrottlingIndex value."""
    _mutate_backup_dict("throttling_backup", backup)


def add_paused_service(name: str) -> None:
    """Register a Windows service that has been paused by NetBoost."""
    services = list(load_state().get("paused_services") or [])
    if name not in services:
        services.append(name)
    _mutate("paused_services", services)


def remove_paused_service(name: str) -> None:
    """Deregister a Windows service after it has been successfully resumed."""
    services = list(load_state().get("paused_services") or [])
    services = [s for s in services if s != name]
    _mutate("paused_services", services)


def add_suspended_pid(pid: int) -> None:
    """Register a process PID that has been suspended by NetBoost."""
    pids = list(load_state().get("suspended_pids") or [])
    if pid not in pids:
        pids.append(pid)
    _mutate("suspended_pids", pids)


def remove_suspended_pid(pid: int) -> None:
    """Deregister a process PID after it has been successfully resumed."""
    pids = list(load_state().get("suspended_pids") or [])
    pids = [p for p in pids if p != pid]
    _mutate("suspended_pids", pids)


def add_qos_policy(name: str) -> None:
    """Register a QoS policy that has been created by NetBoost."""
    policies = list(load_state().get("qos_policies") or [])
    if name not in policies:
        policies.append(name)
    _mutate("qos_policies", policies)


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

    def record_msi_backup(self, backup: dict) -> None:
        record_msi_backup(backup)

    def record_ndu_backup(self, backup: dict) -> None:
        record_ndu_backup(backup)

    def record_throttling_backup(self, backup: dict) -> None:
        record_throttling_backup(backup)

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
