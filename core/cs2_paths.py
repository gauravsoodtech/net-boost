"""
Counter-Strike 2 install discovery and autoexec writer.

Resolves Steam's install root and any additional Steam libraries declared in
``libraryfolders.vdf``, locates the CS2 ``cfg`` directory across them, and
writes NetBoost's recommended ``autoexec.cfg`` atomically with timestamped
backup of any existing file.

All registry/filesystem access is wrapped in try/except so callers can rely
on ``find_cs2_install`` returning ``None`` rather than raising.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Registry / VDF helpers
# ---------------------------------------------------------------------------

_STEAM_REG_PATHS = (
    (r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    (r"SOFTWARE\Valve\Steam",             "InstallPath"),
)
_STEAM_HKCU = (r"Software\Valve\Steam", "SteamPath")

_VDF_PATH_RE = re.compile(r'"path"\s+"([^"]+)"', re.IGNORECASE)


def find_steam_install() -> Optional[str]:
    """Return the absolute path to the Steam install root, or ``None``."""
    try:
        import winreg
    except ImportError:
        return None

    for subkey, value_name in _STEAM_REG_PATHS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                if value:
                    return os.path.normpath(str(value))
        except OSError:
            continue

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STEAM_HKCU[0]) as key:
            value, _ = winreg.QueryValueEx(key, _STEAM_HKCU[1])
            if value:
                return os.path.normpath(str(value))
    except OSError:
        return None

    return None


def find_steam_libraries(steam_root: str) -> list[str]:
    """Return Steam library roots — always includes ``steam_root`` first.

    Parses ``{steam_root}\\steamapps\\libraryfolders.vdf`` if present.
    Unescapes Valve's doubled backslashes (``\\\\`` -> ``\\``).
    """
    libraries: list[str] = [os.path.normpath(steam_root)]
    vdf_path = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return libraries

    for raw in _VDF_PATH_RE.findall(text):
        decoded = raw.replace("\\\\", "\\")
        candidate = os.path.normpath(decoded)
        if candidate and candidate.lower() not in (p.lower() for p in libraries):
            libraries.append(candidate)
    return libraries


# ---------------------------------------------------------------------------
# CS2 install resolution
# ---------------------------------------------------------------------------

_CS2_FOLDER = "Counter-Strike Global Offensive"
_CFG_CANDIDATES = (
    ("game", "csgo", "cfg"),   # current Source 2 layout
    ("csgo", "cfg"),           # legacy
)
_EXE_RELATIVE = ("game", "bin", "win64", "cs2.exe")


def find_cs2_install() -> Optional[tuple[str, str]]:
    """Return ``(cfg_dir, exe_path)`` for the first library containing CS2."""
    steam_root = find_steam_install()
    if not steam_root:
        return None

    for library in find_steam_libraries(steam_root):
        base = os.path.join(library, "steamapps", "common", _CS2_FOLDER)
        if not os.path.isdir(base):
            continue
        for parts in _CFG_CANDIDATES:
            cfg_dir = os.path.join(base, *parts)
            if os.path.isdir(cfg_dir):
                exe_path = os.path.join(base, *_EXE_RELATIVE)
                return (cfg_dir, exe_path)
    return None


# ---------------------------------------------------------------------------
# autoexec.cfg generation + atomic write
# ---------------------------------------------------------------------------

_AUTOEXEC_BODY = """\
// NetBoost — recommended autoexec for Counter-Strike 2.
// Generated automatically. Safe to edit; rerun the writer to refresh.

// Maximum allowed bandwidth budget (CS2 default, set explicitly).
rate 786432

// Restrict matchmaking to servers <= 50 ms ping (raise to 80 for queue speed).
mm_dedicated_search_maxping 50

// Client-side prediction (default; explicit so config changes don't drop it).
cl_predict 1

// Minimum interp window for sub-tick networking.
cl_interp_ratio 1

// Prefer Steam Datagram Relay where available (better routing on bad ISPs).
net_client_steamdatagram_enable_override 1

// Persist updated settings to config.cfg on next clean exit.
host_writeconfig
"""


def recommended_autoexec_text() -> str:
    """Return the recommended ``autoexec.cfg`` body as a string."""
    return _AUTOEXEC_BODY


def write_autoexec(cfg_dir: str, *, overwrite: bool) -> tuple[bool, str]:
    """Write the recommended autoexec.cfg into *cfg_dir* atomically.

    Returns ``(True, written_path)`` on success or ``(False, reason)``.

    If ``autoexec.cfg`` exists and ``overwrite`` is False, returns
    ``(False, "exists:<path>")`` so the caller can prompt the user.
    When overwriting, the existing file is preserved as
    ``autoexec.cfg.bak.<YYYYMMDD-HHMMSS>``.
    """
    if not cfg_dir:
        return (False, "invalid:empty cfg_dir")

    try:
        os.makedirs(cfg_dir, exist_ok=True)
    except OSError as exc:
        logger.error("cs2_paths: cannot create cfg dir %s: %s", cfg_dir, exc)
        return (False, f"mkdir_failed:{exc}")

    target = os.path.join(cfg_dir, "autoexec.cfg")
    if os.path.exists(target):
        if not overwrite:
            return (False, f"exists:{target}")
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = f"{target}.bak.{stamp}"
        try:
            os.replace(target, backup)
            logger.info("cs2_paths: existing autoexec backed up to %s", backup)
        except OSError as exc:
            logger.error("cs2_paths: backup failed for %s: %s", target, exc)
            return (False, f"backup_failed:{exc}")

    tmp = f"{target}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(_AUTOEXEC_BODY)
        os.replace(tmp, target)
    except OSError as exc:
        logger.error("cs2_paths: write failed for %s: %s", target, exc)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return (False, f"write_failed:{exc}")

    logger.info("cs2_paths: wrote %s (%d bytes)", target, len(_AUTOEXEC_BODY))
    return (True, target)
