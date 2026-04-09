"""
nvidia_optimizer.py — NVIDIA RTX 4060 registry and nvidia-smi optimizer for NetBoost.

Applies driver-level power and performance tweaks via registry writes and
optional nvidia-smi calls.  Requires administrator privileges.
"""

import logging
import os
import subprocess
import winreg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Common nvidia-smi search paths
# ---------------------------------------------------------------------------

_NVIDIA_SMI_PATHS = [
    r"C:\Windows\System32\nvidia-smi.exe",
    r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    r"C:\Program Files\NVIDIA Corporation\nvidia-smi.exe",
]

# Registry locations used by this optimizer.
_NVTWEAK_GLOBAL_HKLM = r"SYSTEM\CurrentControlSet\Services\nvlddmkm\Global\NVTweak"
_NVTWEAK_SOFTWARE   = r"SOFTWARE\NVIDIA Corporation\Global\NVTweak"
_VIDEO_BASE         = r"SYSTEM\CurrentControlSet\Control\Video"
_GRAPHICS_DRIVERS   = r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers"


# ---------------------------------------------------------------------------
# Internal registry helpers
# ---------------------------------------------------------------------------

def _read_reg(hive: int, subkey: str, value_name: str):
    """
    Read *value_name* from *hive*\\*subkey*.

    Returns the value or ``None`` if absent.
    """
    try:
        with winreg.OpenKey(hive, subkey, 0, winreg.KEY_QUERY_VALUE) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return value
    except FileNotFoundError:
        return None
    except OSError as exc:
        logger.warning("nvidia_optimizer: read %s: %s", value_name, exc)
        return None


def _write_reg(hive: int, subkey: str, value_name: str, value: int) -> None:
    """
    Write a DWORD *value* to *hive*\\*subkey*\\*value_name*, creating the key
    hierarchy as needed.
    """
    try:
        with winreg.CreateKeyEx(hive, subkey, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, value)
        hive_name = "HKLM" if hive == winreg.HKEY_LOCAL_MACHINE else "HKCU"
        logger.info("nvidia_optimizer: %s\\%s\\%s = %d", hive_name, subkey, value_name, value)
    except OSError as exc:
        logger.error("nvidia_optimizer: write %s: %s", value_name, exc)
        raise


def _delete_reg(hive: int, subkey: str, value_name: str) -> None:
    """Delete *value_name* from *hive*\\*subkey*, ignoring absence."""
    try:
        with winreg.OpenKey(hive, subkey, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, value_name)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("nvidia_optimizer: delete %s: %s", value_name, exc)


def _restore_value(hive: int, subkey: str, value_name: str, original) -> None:
    """Restore *original* value or delete the registry entry if it was absent."""
    if original is None:
        _delete_reg(hive, subkey, value_name)
    else:
        try:
            _write_reg(hive, subkey, value_name, int(original))
        except (OSError, TypeError, ValueError):
            pass


# ---------------------------------------------------------------------------
# GPU key discovery
# ---------------------------------------------------------------------------

def get_gpu_registry_key() -> str | None:
    """
    Enumerate HKLM\\SYSTEM\\CurrentControlSet\\Control\\Video\\ to locate the
    NVIDIA GPU subkey.

    Searches for a ``\\0000`` subkey whose ``Device Description`` or
    ``DriverDesc`` value contains "NVIDIA" or "RTX".

    Returns the full subkey path (e.g. ``"SYSTEM\\...\\{GUID}\\0000"``) or
    ``None`` if not found.
    """
    try:
        video_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            _VIDEO_BASE,
            0,
            winreg.KEY_READ,
        )
    except OSError as exc:
        logger.error("nvidia_optimizer: cannot open Video key: %s", exc)
        return None

    with video_key:
        idx = 0
        while True:
            try:
                guid_name = winreg.EnumKey(video_key, idx)
            except OSError:
                break
            idx += 1

            candidate_path = f"{_VIDEO_BASE}\\{guid_name}\\0000"
            for value_name in ("Device Description", "DriverDesc"):
                desc = _read_reg(winreg.HKEY_LOCAL_MACHINE, candidate_path, value_name)
                if isinstance(desc, str):
                    desc_upper = desc.upper()
                    if "NVIDIA" in desc_upper or "RTX" in desc_upper:
                        logger.info(
                            "nvidia_optimizer: found GPU key at '%s': %s",
                            candidate_path, desc,
                        )
                        return candidate_path

    logger.warning("nvidia_optimizer: no NVIDIA GPU registry key found.")
    return None


# ---------------------------------------------------------------------------
# nvidia-smi helpers
# ---------------------------------------------------------------------------

def is_nvidia_smi_available() -> bool:
    """Return ``True`` if nvidia-smi.exe is present at a known location."""
    for path in _NVIDIA_SMI_PATHS:
        if os.path.isfile(path):
            return True
    # Also try PATH.
    import shutil
    return shutil.which("nvidia-smi") is not None


def _find_nvidia_smi() -> str:
    """Return the path to nvidia-smi.exe or raise FileNotFoundError."""
    for path in _NVIDIA_SMI_PATHS:
        if os.path.isfile(path):
            return path
    import shutil
    found = shutil.which("nvidia-smi")
    if found:
        return found
    raise FileNotFoundError("nvidia-smi.exe not found.")


def run_nvidia_smi(args: list) -> str:
    """
    Run nvidia-smi with *args* and return stdout.

    Raises :class:`subprocess.CalledProcessError` or :class:`FileNotFoundError`
    on failure.
    """
    smi = _find_nvidia_smi()
    cmd = [smi] + [str(a) for a in args]
    logger.debug("nvidia_optimizer: running %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, output=result.stdout, stderr=result.stderr
        )
    return result.stdout


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply(settings: dict) -> dict:
    """
    Apply NVIDIA optimizations described in *settings*.

    Settings keys consumed (all bool):
    - ``dynamic_pstate_off`` — DisableDynamicPstate=1
    - ``ull_mode``           — ULMDMode=1
    - ``max_power``          — PowerMizerEnable=0, PowerMizerLevel=1

    Also runs ``nvidia-smi -pm 1`` (persistent mode) when nvidia-smi is
    available.

    Returns a *backup* dict suitable for :func:`restore`.
    """
    backup: dict = {"_registry": []}
    gpu_key = get_gpu_registry_key()

    def _backup_and_write(subkey, vname, new_val):
        original = _read_reg(winreg.HKEY_LOCAL_MACHINE, subkey, vname)
        backup["_registry"].append({
            "hive": "hklm", "subkey": subkey,
            "value_name": vname, "original": original,
        })
        try:
            _write_reg(winreg.HKEY_LOCAL_MACHINE, subkey, vname, new_val)
        except OSError:
            pass

    # --- Dynamic P-State ---
    if settings.get("dynamic_pstate_off"):
        _backup_and_write(_NVTWEAK_GLOBAL_HKLM, "DisableDynamicPstate", 1)

    # --- Ultra-low latency mode (DX submission depth) ---
    if settings.get("ull_mode"):
        _backup_and_write(_NVTWEAK_SOFTWARE, "ULMDMode", 1)

    # --- Max power / disable PowerMizer ---
    if settings.get("max_power") and gpu_key:
        for vname, new_val in (("PowerMizerEnable", 0), ("PowerMizerLevel", 1)):
            _backup_and_write(gpu_key, vname, new_val)

    # --- Hardware-Accelerated GPU Scheduling (HAGS) ---
    # HwSchMode: 2 = enabled (default), 1 = disabled
    if settings.get("disable_hags"):
        _backup_and_write(_GRAPHICS_DRIVERS, "HwSchMode", 1)
        logger.info("nvidia_optimizer: HAGS disabled (requires reboot to take effect).")

    # --- nvidia-smi persistent mode ---
    smi_available = is_nvidia_smi_available()
    if smi_available:
        try:
            run_nvidia_smi(["-pm", "1"])
            backup["_nvidia_smi_pm_applied"] = True
            logger.info("nvidia_optimizer: nvidia-smi persistent mode enabled.")
        except Exception as exc:
            logger.warning("nvidia_optimizer: nvidia-smi -pm 1 failed: %s", exc)

    logger.info("nvidia_optimizer: apply() complete.")
    return backup


def restore(backup: dict) -> None:
    """
    Restore NVIDIA registry values from *backup* (as returned by :func:`apply`).

    Handles both V2 structured format (``_registry`` list of dicts) and
    legacy V1 compound-string format (``"hklm:<subkey>:<vname>"`` keys).
    Also disables nvidia-smi persistent mode if it was enabled.
    """
    # V2 structured format
    for entry in backup.get("_registry", []):
        subkey = entry.get("subkey", "")
        vname = entry.get("value_name", "")
        original = entry.get("original")
        if subkey and vname:
            _restore_value(winreg.HKEY_LOCAL_MACHINE, subkey, vname, original)

    # Legacy V1 compound-string format (for state.json compatibility)
    for compound_key, original in backup.items():
        if compound_key.startswith("_"):
            continue
        if not isinstance(compound_key, str) or ":" not in compound_key:
            continue
        parts = compound_key.split(":", 2)
        if len(parts) != 3:
            continue
        _, subkey, vname = parts
        _restore_value(winreg.HKEY_LOCAL_MACHINE, subkey, vname, original)

    if backup.get("_nvidia_smi_pm_applied"):
        try:
            run_nvidia_smi(["-pm", "0"])
            logger.info("nvidia_optimizer: nvidia-smi persistent mode disabled.")
        except Exception as exc:
            logger.warning("nvidia_optimizer: nvidia-smi -pm 0 failed: %s", exc)

    logger.info("nvidia_optimizer: restore() complete.")


# ---------------------------------------------------------------------------
# NvidiaOptimizer class — object-oriented wrapper used by the UI
# ---------------------------------------------------------------------------

class NvidiaOptimizer:
    """Object-oriented interface for NVIDIA optimization (wraps module functions)."""

    def apply(self, settings: dict) -> dict:
        return apply(settings)

    def restore(self, backup: dict) -> None:
        restore(backup)
