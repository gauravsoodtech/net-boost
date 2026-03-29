"""
fps_booster.py — FPS and system-level optimizer for NetBoost.

Applies power plan changes, P-core affinity, timer resolution, Game DVR
disabling, SysMain service stopping, visual-effects suppression, and
fullscreen optimization disabling for a target game process.

All operations use graceful try/except fallbacks so that a failure in one
step does not block the rest.  Requires administrator privileges for most
operations.
"""

import ctypes
import ctypes.wintypes
import logging
import os
import subprocess
import winreg

import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ULTIMATE_PERF_GUID = "e9a42b02-d5df-448d-aa00-03f14749eb61"
PROCESS_ALL_ACCESS = 0x1F0FFF

# Registry paths
_GAME_DVR_KEY      = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
_APP_COMPAT_LAYERS = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"

# ctypes / Win32 constants
_SPI_SETANIMATION = 0x0049


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _get_process_path(pid: int) -> str:
    """Return the executable path of process *pid* via psutil."""
    return psutil.Process(pid).exe()


def detect_hybrid_cpu_p_core_mask() -> int:
    """
    Return a CPU affinity bitmask that covers only Performance (P) cores.

    For the Intel Core i7-13650HX (6 P-cores, 8 E-cores) P-core threads are
    0-11 (6 physical P-cores × 2 HT threads), giving mask 0x0FFF.

    If the current CPU is identified as 13th-gen Intel (ProcessorNameString
    contains "13"), return 0x0FFF; otherwise return 0xFFFFFFFF (all cores) as
    a safe fallback.
    """
    try:
        proc_name = _read_hklm(
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            "ProcessorNameString",
        )
        if isinstance(proc_name, str) and "13" in proc_name:
            logger.debug("detect_hybrid_cpu_p_core_mask: 13th-gen detected, mask=0x0FFF")
            return 0x0FFF
    except Exception as exc:
        logger.debug("detect_hybrid_cpu_p_core_mask: registry read failed: %s", exc)

    logger.debug("detect_hybrid_cpu_p_core_mask: fallback mask=0xFFFFFFFF")
    return 0xFFFFFFFF


def _read_hklm(subkey: str, value_name: str):
    """Read a registry value from HKLM.  Returns the value or None."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, subkey, 0, winreg.KEY_QUERY_VALUE
        ) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return value
    except OSError:
        return None


def _write_hkcu(subkey: str, value_name: str, value: int,
                value_type: int = winreg.REG_DWORD) -> None:
    """Write a registry value to HKCU, creating the key if needed."""
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, value_name, 0, value_type, value)
    logger.info("fps_booster: HKCU\\%s\\%s = %r", subkey, value_name, value)


def _read_hkcu(subkey: str, value_name: str):
    """Read a registry value from HKCU.  Returns (value, type) or None."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_QUERY_VALUE
        ) as key:
            return winreg.QueryValueEx(key, value_name)
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("fps_booster: HKCU read %s: %s", value_name, exc)
        return None


def _delete_hkcu(subkey: str, value_name: str) -> None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, value_name)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("fps_booster: HKCU delete %s: %s", value_name, exc)


# ---------------------------------------------------------------------------
# Affinity & timer
# ---------------------------------------------------------------------------

def set_p_core_affinity(pid: int) -> int:
    """
    Set P-core affinity on *pid* via ``SetProcessAffinityMask``.

    Returns the old affinity mask.  Raises ``OSError`` on failure.
    """
    mask = detect_hybrid_cpu_p_core_mask()
    kernel32 = ctypes.windll.kernel32

    handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not handle:
        raise OSError(f"OpenProcess failed for PID {pid}")

    old_mask = ctypes.c_size_t(0)
    system_mask = ctypes.c_size_t(0)

    # GetProcessAffinityMask to save the current value.
    kernel32.GetProcessAffinityMask(
        handle,
        ctypes.byref(old_mask),
        ctypes.byref(system_mask),
    )

    if not kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(mask)):
        kernel32.CloseHandle(handle)
        raise OSError(f"SetProcessAffinityMask failed for PID {pid}")

    kernel32.CloseHandle(handle)
    logger.info("fps_booster: PID %d affinity set to 0x%X (was 0x%X)", pid, mask, old_mask.value)
    return old_mask.value


def set_timer_resolution(interval_100ns: int) -> None:
    """
    Set the Windows timer resolution to *interval_100ns* (units of 100 ns).

    Calls ``ntdll.NtSetTimerResolution``.  A value of 5000 gives ~0.5 ms.
    """
    ntdll = ctypes.windll.ntdll
    current = ctypes.c_ulong(0)
    status = ntdll.NtSetTimerResolution(
        ctypes.c_ulong(interval_100ns),
        ctypes.c_bool(True),
        ctypes.byref(current),
    )
    if status != 0:
        raise OSError(f"NtSetTimerResolution failed with NTSTATUS 0x{status:08X}")
    logger.info("fps_booster: timer resolution set to %d × 100ns.", interval_100ns)


# ---------------------------------------------------------------------------
# Power plan helpers
# ---------------------------------------------------------------------------

def get_active_power_plan() -> str:
    """
    Return the GUID of the currently active power plan.

    Parses the output of ``powercfg /getactivescheme``.
    """
    result = subprocess.run(
        ["powercfg", "/getactivescheme"],
        capture_output=True, text=True, timeout=10,
    )
    import re
    match = re.search(
        r"Power Scheme GUID:\s+([0-9a-fA-F\-]{36})",
        result.stdout,
    )
    if match:
        return match.group(1)
    return result.stdout.strip()


def set_power_plan(guid: str) -> None:
    """Activate the power plan identified by *guid*."""
    subprocess.run(
        ["powercfg", "/setactive", guid],
        check=True, capture_output=True, text=True, timeout=10,
    )
    logger.info("fps_booster: power plan set to %s.", guid)


def _ensure_ultimate_perf_plan() -> str:
    """
    Ensure the Ultimate Performance plan exists and return its GUID.

    Tries ``powercfg /duplicatescheme`` first; falls back to the built-in
    SCHEME_MIN (High Performance) if that fails.
    """
    try:
        result = subprocess.run(
            ["powercfg", "/duplicatescheme", ULTIMATE_PERF_GUID],
            capture_output=True, text=True, timeout=10,
        )
        import re
        match = re.search(r"([0-9a-fA-F\-]{36})", result.stdout)
        if match:
            new_guid = match.group(1)
            logger.info("fps_booster: Ultimate Performance plan duplicated: %s", new_guid)
            return new_guid
    except Exception as exc:
        logger.warning("fps_booster: could not duplicate Ultimate Performance plan: %s", exc)

    # Fall back to High Performance (SCHEME_MIN).
    return "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"


# ---------------------------------------------------------------------------
# SysMain (Superfetch) service
# ---------------------------------------------------------------------------

def _stop_sysmain() -> bool:
    """Stop the SysMain service.  Returns True if stopped successfully."""
    try:
        import win32service
        import win32serviceutil
        state = win32serviceutil.QueryServiceStatus("SysMain")[1]
        if state == win32service.SERVICE_STOPPED:
            return False  # Already stopped — nothing to undo.
        win32serviceutil.StopService("SysMain")
        logger.info("fps_booster: SysMain service stopped.")
        return True
    except Exception as exc:
        logger.warning("fps_booster: could not stop SysMain: %s", exc)
        return False


def _start_sysmain() -> None:
    try:
        import win32serviceutil
        win32serviceutil.StartService("SysMain")
        logger.info("fps_booster: SysMain service started.")
    except Exception as exc:
        logger.warning("fps_booster: could not start SysMain: %s", exc)


# ---------------------------------------------------------------------------
# Visual effects
# ---------------------------------------------------------------------------

def _disable_animations() -> None:
    """Suppress window animations via SystemParametersInfo."""
    class ANIMATIONINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("iMinAnimate", ctypes.c_int)]

    ai = ANIMATIONINFO()
    ai.cbSize = ctypes.sizeof(ANIMATIONINFO)
    ai.iMinAnimate = 0
    ctypes.windll.user32.SystemParametersInfoW(
        _SPI_SETANIMATION, ctypes.sizeof(ANIMATIONINFO), ctypes.byref(ai), 3
    )
    logger.info("fps_booster: window animations disabled.")


def _enable_animations() -> None:
    class ANIMATIONINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("iMinAnimate", ctypes.c_int)]

    ai = ANIMATIONINFO()
    ai.cbSize = ctypes.sizeof(ANIMATIONINFO)
    ai.iMinAnimate = 1
    ctypes.windll.user32.SystemParametersInfoW(
        _SPI_SETANIMATION, ctypes.sizeof(ANIMATIONINFO), ctypes.byref(ai), 3
    )
    logger.info("fps_booster: window animations re-enabled.")


# ---------------------------------------------------------------------------
# Fullscreen optimisation (AppCompatFlags)
# ---------------------------------------------------------------------------

def _set_fullscreen_opt(game_exe_path: str, disable: bool) -> str | None:
    """
    Add or remove DISABLEDXMAXIMIZEDWINDOWEDMODE from AppCompatFlags\\Layers.

    Returns the previous value string, or None if it was absent.
    """
    try:
        prev = _read_hkcu(_APP_COMPAT_LAYERS, game_exe_path)
        if disable:
            existing = prev[0] if prev else ""
            flag = "DISABLEDXMAXIMIZEDWINDOWEDMODE"
            if flag not in existing:
                new_val = (existing + " " + flag).strip()
                _write_hkcu(_APP_COMPAT_LAYERS, game_exe_path, new_val, winreg.REG_SZ)
            logger.info("fps_booster: fullscreen optimisation disabled for '%s'.", game_exe_path)
        return prev[0] if prev else None
    except Exception as exc:
        logger.warning("fps_booster: fullscreen opt change failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply(settings: dict, game_pid: int = None) -> dict:
    """
    Apply FPS and system optimizations according to *settings*.

    Settings keys consumed:
    - ``power_plan``        — switch to Ultimate Performance plan
    - ``pcores_affinity``   — set P-core affinity on *game_pid*
    - ``timer_resolution``  — set 0.5 ms timer resolution
    - ``game_dvr_off``      — disable Windows Game DVR
    - ``sysmain_off``       — stop SysMain service
    - ``visual_effects_off``— disable window animations
    - ``fullscreen_opt_off``— add DISABLEDXMAXIMIZEDWINDOWEDMODE for game exe

    Returns a *backup* dict suitable for :func:`restore`.
    """
    backup: dict = {}

    # --- Power plan ---
    if settings.get("power_plan"):
        try:
            current_plan = get_active_power_plan()
            backup["power_plan"] = current_plan
            target_guid = _ensure_ultimate_perf_plan()
            set_power_plan(target_guid)
            backup["power_plan_applied"] = target_guid
        except Exception as exc:
            logger.error("fps_booster: power plan change failed: %s", exc)

    # --- P-core affinity ---
    if settings.get("pcores_affinity") and game_pid is not None:
        try:
            old_mask = set_p_core_affinity(game_pid)
            backup["affinity_pid"]  = game_pid
            backup["affinity_mask"] = old_mask
        except Exception as exc:
            logger.error("fps_booster: affinity change failed for PID %d: %s", game_pid, exc)

    # --- Timer resolution ---
    if settings.get("timer_resolution"):
        try:
            set_timer_resolution(5000)  # 0.5 ms
            backup["timer_resolution_applied"] = True
        except Exception as exc:
            logger.error("fps_booster: timer resolution change failed: %s", exc)

    # --- Game DVR ---
    if settings.get("game_dvr_off"):
        try:
            prev = _read_hkcu(_GAME_DVR_KEY, "AppCaptureEnabled")
            backup["game_dvr_prev"] = prev  # (value, type) or None
            _write_hkcu(_GAME_DVR_KEY, "AppCaptureEnabled", 0)
        except Exception as exc:
            logger.error("fps_booster: Game DVR disable failed: %s", exc)

    # --- SysMain ---
    if settings.get("sysmain_off"):
        try:
            was_running = _stop_sysmain()
            backup["sysmain_was_running"] = was_running
        except Exception as exc:
            logger.error("fps_booster: SysMain stop failed: %s", exc)

    # --- Visual effects ---
    if settings.get("visual_effects_off"):
        try:
            _disable_animations()
            backup["visual_effects_disabled"] = True
        except Exception as exc:
            logger.error("fps_booster: visual effects disable failed: %s", exc)

    # --- Fullscreen optimisation ---
    if settings.get("fullscreen_opt_off") and game_pid is not None:
        try:
            game_exe = _get_process_path(game_pid)
            prev_layer = _set_fullscreen_opt(game_exe, disable=True)
            backup["fullscreen_opt_game_exe"] = game_exe
            backup["fullscreen_opt_prev"]     = prev_layer
        except Exception as exc:
            logger.error("fps_booster: fullscreen opt disable failed: %s", exc)

    logger.info("fps_booster: apply() complete.")
    return backup


def restore(backup: dict) -> None:
    """
    Reverse all changes recorded in *backup* (as returned by :func:`apply`).

    Each operation is individually try/except guarded.
    """
    # --- Power plan ---
    if "power_plan" in backup:
        try:
            set_power_plan(backup["power_plan"])
        except Exception as exc:
            logger.error("fps_booster: restore power plan failed: %s", exc)

    # --- P-core affinity ---
    if "affinity_pid" in backup:
        try:
            pid      = backup["affinity_pid"]
            old_mask = backup.get("affinity_mask", 0xFFFFFFFF)
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
            if handle:
                kernel32.SetProcessAffinityMask(handle, ctypes.c_size_t(old_mask))
                kernel32.CloseHandle(handle)
                logger.info("fps_booster: PID %d affinity restored to 0x%X.", pid, old_mask)
        except Exception as exc:
            logger.error("fps_booster: restore affinity failed: %s", exc)

    # --- Timer resolution (restore to default 15.625 ms = 156250 × 100ns) ---
    if backup.get("timer_resolution_applied"):
        try:
            set_timer_resolution(156250)
        except Exception as exc:
            logger.warning("fps_booster: restore timer resolution failed: %s", exc)

    # --- Game DVR ---
    if "game_dvr_prev" in backup:
        try:
            prev = backup["game_dvr_prev"]
            if prev is None:
                _delete_hkcu(_GAME_DVR_KEY, "AppCaptureEnabled")
            else:
                value, vtype = prev
                _write_hkcu(_GAME_DVR_KEY, "AppCaptureEnabled", value, vtype)
        except Exception as exc:
            logger.error("fps_booster: restore Game DVR failed: %s", exc)

    # --- SysMain ---
    if backup.get("sysmain_was_running"):
        try:
            _start_sysmain()
        except Exception as exc:
            logger.error("fps_booster: restore SysMain failed: %s", exc)

    # --- Visual effects ---
    if backup.get("visual_effects_disabled"):
        try:
            _enable_animations()
        except Exception as exc:
            logger.error("fps_booster: restore visual effects failed: %s", exc)

    # --- Fullscreen optimisation ---
    if "fullscreen_opt_game_exe" in backup:
        try:
            game_exe = backup["fullscreen_opt_game_exe"]
            prev_val = backup.get("fullscreen_opt_prev")
            if prev_val is None:
                _delete_hkcu(_APP_COMPAT_LAYERS, game_exe)
            else:
                _write_hkcu(_APP_COMPAT_LAYERS, game_exe, prev_val, winreg.REG_SZ)
        except Exception as exc:
            logger.error("fps_booster: restore fullscreen opt failed: %s", exc)

    logger.info("fps_booster: restore() complete.")


# ---------------------------------------------------------------------------
# FpsBooster class — object-oriented wrapper used by the UI
# ---------------------------------------------------------------------------

class FpsBooster:
    """Object-oriented interface for FPS/system optimization (wraps module functions)."""

    def apply(self, settings: dict, game_pid: int = None) -> dict:
        return apply(settings, game_pid=game_pid)

    def restore(self, backup: dict) -> None:
        restore(backup)

    def get_active_power_plan(self) -> str:
        return get_active_power_plan()

    def set_power_plan(self, guid: str) -> None:
        set_power_plan(guid)

    def set_p_core_affinity(self, pid: int) -> int:
        return set_p_core_affinity(pid)

    def set_timer_resolution(self, interval_100ns: int) -> None:
        set_timer_resolution(interval_100ns)
