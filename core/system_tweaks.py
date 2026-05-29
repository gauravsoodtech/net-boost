"""
system_tweaks.py — System-level perf tweaks that don't fit any existing optimizer:

* Force MSI Mode for the discrete GPU (NVIDIA) and the Wi-Fi NIC (Intel).
* Disable the NDU (Network Data Usage) service.
* Disable Windows multimedia network throttling (NetworkThrottlingIndex).

All three take effect across the system after a reboot (NDU and MSI Mode
require it; NetworkThrottlingIndex applies to new sockets only). Restore
paths reverse the writes deterministically using the value captured at
apply time.

Requires administrator privileges; writes under HKLM\\SYSTEM\\... may also
need SeBackupPrivilege on hardened systems. Failures are surfaced via the
``_access_denied`` flag on the backup dict so the UI can warn the user.
"""

from __future__ import annotations

import logging
import subprocess
import winreg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PCI_ENUM_BASE = r"SYSTEM\CurrentControlSet\Enum\PCI"
MSI_SUBPATH = r"Device Parameters\Interrupt Management\MessageSignaledInterruptProperties"
MSI_VALUE_NAME = "MSISupported"
MSI_SENTINEL_ABSENT = -1  # backup marker meaning "key did not exist before apply"

# Class GUIDs we care about under PCI\VEN_xxxx&DEV_xxxx\<instance>\ClassGUID.
_DISPLAY_CLASS_GUID = "{4d36e968-e325-11ce-bfc1-08002be10318}"
_NET_CLASS_GUID = "{4d36e972-e325-11ce-bfc1-08002be10318}"

# Driver Service names that mark a device as relevant.
_NVIDIA_SERVICE_PREFIXES = ("nvlddmkm",)            # NVIDIA Display kernel-mode driver
_INTEL_WIFI_SERVICE_PREFIXES = ("Netwtw",)          # AX201/AX210/AX211 driver family

NDU_REG_PATH = r"SYSTEM\CurrentControlSet\Services\Ndu"
NDU_VALUE_NAME = "Start"

THROTTLING_REG_PATH = (
    r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile"
)
THROTTLING_VALUE_NAME = "NetworkThrottlingIndex"
THROTTLING_DISABLED = 0xFFFFFFFF


# ---------------------------------------------------------------------------
# Generic registry helpers (kept private so tests can monkeypatch them)
# ---------------------------------------------------------------------------

def _read_reg(subkey: str, value_name: str):
    """Read *value_name* from HKLM\\*subkey*; ``None`` if absent or unreadable."""
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
        logger.warning("system_tweaks: cannot read HKLM\\%s\\%s: %s", subkey, value_name, exc)
        return None


def _write_reg_dword(subkey: str, value_name: str, value: int) -> None:
    """Write DWORD *value* to HKLM\\*subkey*\\*value_name*. Creates the subkey if needed."""
    # CreateKey opens or creates; SetValueEx writes; closes on exit.
    with winreg.CreateKeyEx(
        winreg.HKEY_LOCAL_MACHINE,
        subkey,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        winreg.SetValueEx(key, value_name, 0, winreg.REG_DWORD, value)
    logger.info("system_tweaks: HKLM\\%s\\%s = 0x%X", subkey, value_name, value)


def _delete_reg_value(subkey: str, value_name: str) -> None:
    """Delete *value_name* under HKLM\\*subkey*; silent if absent."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            subkey,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            winreg.DeleteValue(key, value_name)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("system_tweaks: cannot delete HKLM\\%s\\%s: %s", subkey, value_name, exc)


def _enum_subkeys(subkey: str) -> list[str]:
    """Return immediate child key names of HKLM\\*subkey*."""
    names: list[str] = []
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            subkey,
            0,
            winreg.KEY_READ,
        ) as key:
            idx = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, idx))
                except OSError:
                    break
                idx += 1
    except OSError as exc:
        logger.warning("system_tweaks: cannot enumerate HKLM\\%s: %s", subkey, exc)
    return names


# ---------------------------------------------------------------------------
# MSI Mode — PCI device enumeration
# ---------------------------------------------------------------------------

def _is_target_device(instance_subkey: str) -> bool:
    """
    Decide whether the device described by *instance_subkey* should receive
    MSI Mode. Matches NVIDIA Display devices and Intel Wi-Fi NICs.

    Match strategy (any one is sufficient):
    * ``Service`` value starts with a known driver prefix.
    * ``ClassGUID`` matches the Display class (any GPU). The discrete GPU
      will be the only NVIDIA Display device on this laptop.
    * For Net class, additionally require Intel Wi-Fi driver service to
      avoid touching the Ethernet adapter.
    """
    service = _read_reg(instance_subkey, "Service")
    class_guid = _read_reg(instance_subkey, "ClassGUID")

    if isinstance(service, str):
        svc = service.strip()
        if any(svc.startswith(p) for p in _NVIDIA_SERVICE_PREFIXES):
            return True
        if any(svc.startswith(p) for p in _INTEL_WIFI_SERVICE_PREFIXES):
            return True

    if isinstance(class_guid, str):
        guid = class_guid.strip().lower()
        # Display class — any GPU (we accept this; on a hybrid laptop the
        # iGPU is iGFX-class and is fine to leave alone, but writing MSI=1
        # to it as well does not regress anything observable).
        if guid == _DISPLAY_CLASS_GUID:
            return True

    return False


def _discover_msi_target_paths() -> list[str]:
    """
    Walk PCI device tree and return the list of
    ``Device Parameters\\Interrupt Management\\MessageSignaledInterruptProperties``
    subkey paths for every targeted device.
    """
    targets: list[str] = []
    for vendor_dev in _enum_subkeys(PCI_ENUM_BASE):
        # vendor_dev looks like "VEN_10DE&DEV_28A0&SUBSYS_xxxx&REV_xx".
        vendor_subkey = f"{PCI_ENUM_BASE}\\{vendor_dev}"
        for instance in _enum_subkeys(vendor_subkey):
            instance_subkey = f"{vendor_subkey}\\{instance}"
            if not _is_target_device(instance_subkey):
                continue
            msi_subkey = f"{instance_subkey}\\{MSI_SUBPATH}"
            targets.append(msi_subkey)
    return targets


def apply_msi_mode_all() -> dict:
    """
    Force MSI Mode on every targeted PCI device.

    Returns a backup dict::

        {
            "values": {
                "<msi_subkey_path>": <prior MSISupported value or -1 if absent>,
                ...
            },
            "_access_denied": bool,  # True if any write hit a permission error
            "_targets_found": int,
            "_writes_succeeded": int,
        }
    """
    backup: dict = {
        "values": {},
        "_access_denied": False,
        "_targets_found": 0,
        "_writes_succeeded": 0,
    }

    targets = _discover_msi_target_paths()
    backup["_targets_found"] = len(targets)
    if not targets:
        logger.warning("system_tweaks: no MSI-capable target devices discovered.")
        return backup

    for msi_subkey in targets:
        prior = _read_reg(msi_subkey, MSI_VALUE_NAME)
        backup["values"][msi_subkey] = (
            MSI_SENTINEL_ABSENT if prior is None else int(prior)
        )
        try:
            _write_reg_dword(msi_subkey, MSI_VALUE_NAME, 1)
            backup["_writes_succeeded"] += 1
        except PermissionError as exc:
            logger.warning(
                "system_tweaks: MSI write denied for %s — needs SYSTEM-level "
                "registry permission (%s)", msi_subkey, exc,
            )
            backup["_access_denied"] = True
        except OSError as exc:
            logger.warning("system_tweaks: MSI write failed for %s: %s", msi_subkey, exc)

    logger.info(
        "system_tweaks: MSI Mode applied to %d/%d target(s).",
        backup["_writes_succeeded"], backup["_targets_found"],
    )
    return backup


def restore_msi_mode(backup: dict) -> None:
    """Reverse ``apply_msi_mode_all`` using the captured prior values."""
    values = (backup or {}).get("values") or {}
    if not values:
        return
    for msi_subkey, prior in values.items():
        try:
            if prior == MSI_SENTINEL_ABSENT:
                _delete_reg_value(msi_subkey, MSI_VALUE_NAME)
            else:
                _write_reg_dword(msi_subkey, MSI_VALUE_NAME, int(prior))
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("system_tweaks: MSI restore failed for %s: %s", msi_subkey, exc)


# ---------------------------------------------------------------------------
# NDU service
# ---------------------------------------------------------------------------

def _sc_config(start_value: str) -> tuple[bool, str]:
    """Invoke ``sc.exe config Ndu start=<value>``. Returns (ok, stderr)."""
    try:
        result = subprocess.run(
            ["sc.exe", "config", "Ndu", f"start={start_value}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, str(exc)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "").strip()
    return True, ""


def disable_ndu_service() -> dict:
    """
    Disable the NDU service so Win11's network-data-usage tracker does not
    interfere with the network stack on the next boot.

    Returns backup::

        {"start": <prior Start DWORD or None>, "_ok": bool, "_error": str}
    """
    prior = _read_reg(NDU_REG_PATH, NDU_VALUE_NAME)
    backup: dict = {"start": prior, "_ok": False, "_error": ""}

    ok, err = _sc_config("disabled")
    if not ok:
        backup["_error"] = err
        logger.warning("system_tweaks: sc config Ndu start=disabled failed: %s", err)
        return backup

    backup["_ok"] = True
    logger.info("system_tweaks: NDU service disabled (prior Start=%s).", prior)
    return backup


def restore_ndu_service(backup: dict) -> None:
    """Reverse ``disable_ndu_service`` using the captured prior Start value."""
    prior = (backup or {}).get("start")
    if prior is None:
        # The Win11 default is 2 (auto). Use ``demand`` (= 3) as a safer
        # conservative fallback so the service can still wake on demand if
        # the prior value is unknown.
        target = "demand"
    else:
        target = {
            0: "boot",
            1: "system",
            2: "auto",
            3: "demand",
            4: "disabled",
        }.get(int(prior), "demand")

    ok, err = _sc_config(target)
    if ok:
        logger.info("system_tweaks: NDU service restored to start=%s.", target)
    else:
        logger.warning("system_tweaks: NDU restore (start=%s) failed: %s", target, err)


# ---------------------------------------------------------------------------
# NetworkThrottlingIndex
# ---------------------------------------------------------------------------

def disable_network_throttling() -> dict:
    """
    Disable Windows multimedia network throttling system-wide. Effective on
    new sockets immediately; fully effective on reboot.

    Returns backup::

        {"prev_value": <prior DWORD or None>, "_ok": bool}
    """
    prior = _read_reg(THROTTLING_REG_PATH, THROTTLING_VALUE_NAME)
    backup: dict = {"prev_value": prior, "_ok": False}

    try:
        _write_reg_dword(THROTTLING_REG_PATH, THROTTLING_VALUE_NAME, THROTTLING_DISABLED)
        backup["_ok"] = True
    except OSError as exc:
        logger.warning("system_tweaks: NetworkThrottlingIndex write failed: %s", exc)

    return backup


def restore_network_throttling(backup: dict) -> None:
    """Reverse ``disable_network_throttling`` using the captured prior value."""
    prior = (backup or {}).get("prev_value")
    if prior is None:
        _delete_reg_value(THROTTLING_REG_PATH, THROTTLING_VALUE_NAME)
        return
    try:
        _write_reg_dword(THROTTLING_REG_PATH, THROTTLING_VALUE_NAME, int(prior))
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("system_tweaks: NetworkThrottlingIndex restore failed: %s", exc)
