"""
ram_optimizer.py — RAM / working-set optimizer for NetBoost.

Trims process working sets and flushes the system file cache to reclaim
physical RAM that can then be used by a game.

Requires administrator privileges (SeIncreaseQuotaPrivilege and
SeProfileSingleProcessPrivilege) for :func:`flush_file_cache`; working-set
trimming of other processes requires PROCESS_VM_OPERATION access which is
generally available with admin rights.
"""

import ctypes
import ctypes.wintypes
import logging
import os

import psutil

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CRITICAL_PROCESSES: set[str] = {
    "System",
    "csrss.exe",
    "smss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "svchost.exe",
}

# Win32 access-right flags
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_OPERATION      = 0x0008
_OPEN_FLAGS                = _PROCESS_QUERY_INFORMATION | _PROCESS_VM_OPERATION

# SetSystemFileCacheSize flag — FILE_CACHE_MAX_HARD_ENABLE flushes standby RAM
_FILE_CACHE_MAX_HARD_ENABLE = 0x2  # 0x200 in older SDK docs; corrected value below

# The actual flag value documented in the Windows SDK:
# FILE_CACHE_MAX_HARD_ENABLE = 0x2  (combined with FileCacheMaximumHardLimit = 0)
# Some references list 0x200 — we keep both and use 0x2 (matches SDK constant).
_SET_CACHE_FLAGS = 0x2


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_free_ram_mb() -> int:
    """Return available physical RAM in MiB."""
    return psutil.virtual_memory().available // (1024 * 1024)


# ---------------------------------------------------------------------------
# Working-set trimming
# ---------------------------------------------------------------------------

def empty_process_working_sets() -> None:
    """
    Iterate all processes and ask Windows to trim each one's working set.

    Skips critical system processes and the current process.  Permission
    errors are silently swallowed on a per-process basis.
    """
    kernel32 = ctypes.windll.kernel32
    current_pid = os.getpid()

    for proc in psutil.process_iter(["name", "pid"]):
        try:
            name = proc.info["name"] or ""
            pid  = proc.info["pid"]

            if pid == current_pid:
                continue
            if name in CRITICAL_PROCESSES:
                continue

            handle = kernel32.OpenProcess(_OPEN_FLAGS, False, pid)
            if not handle:
                continue

            try:
                # EmptyWorkingSet(handle) — trims the process working set.
                result = kernel32.K32EmptyWorkingSet(handle)
                if not result:
                    # Fall back to the older export name on some Windows versions.
                    kernel32.EmptyWorkingSet(handle)
            finally:
                kernel32.CloseHandle(handle)

        except PermissionError:
            pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        except Exception as exc:
            logger.debug("ram_optimizer: skipping PID %s: %s", proc.info.get("pid"), exc)

    logger.info("ram_optimizer: process working-set trim complete.")


# ---------------------------------------------------------------------------
# File-cache flush
# ---------------------------------------------------------------------------

def flush_file_cache() -> None:
    """
    Flush the Windows standby (file) cache by calling
    ``SetSystemFileCacheSize(0, 0, FILE_CACHE_MAX_HARD_ENABLE)``.

    This forces Windows to release file-cache memory so it becomes available
    to applications.

    Requires ``SeIncreaseQuotaPrivilege``.
    """
    kernel32 = ctypes.windll.kernel32
    # Prototype: BOOL SetSystemFileCacheSize(SIZE_T Min, SIZE_T Max, DWORD Flags)
    kernel32.SetSystemFileCacheSize.restype  = ctypes.wintypes.BOOL
    kernel32.SetSystemFileCacheSize.argtypes = [
        ctypes.c_size_t,        # MinimumFileCacheSize
        ctypes.c_size_t,        # MaximumFileCacheSize
        ctypes.wintypes.DWORD,  # Flags
    ]

    success = kernel32.SetSystemFileCacheSize(0, 0, _SET_CACHE_FLAGS)
    if success:
        logger.info("ram_optimizer: system file cache flushed.")
    else:
        err = kernel32.GetLastError()
        logger.warning("ram_optimizer: SetSystemFileCacheSize failed (error %d).", err)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def optimize() -> dict:
    """
    Run the full RAM optimization pass.

    1. Record available RAM before.
    2. Trim all non-critical process working sets.
    3. Flush the system file cache.
    4. Record available RAM after.

    Returns::

        {
            "before_mb": int,   # available RAM before optimization
            "after_mb":  int,   # available RAM after optimization
            "freed_mb":  int,   # delta (may be negative if OS re-allocates)
        }
    """
    before_mb = _get_free_ram_mb()
    logger.info("ram_optimizer: available RAM before = %d MiB", before_mb)

    empty_process_working_sets()
    flush_file_cache()

    after_mb  = _get_free_ram_mb()
    freed_mb  = after_mb - before_mb
    logger.info(
        "ram_optimizer: available RAM after = %d MiB (freed ~%d MiB).",
        after_mb, freed_mb,
    )

    return {
        "before_mb": before_mb,
        "after_mb":  after_mb,
        "freed_mb":  freed_mb,
    }


# ---------------------------------------------------------------------------
# RamOptimizer class — object-oriented wrapper used by the UI
# ---------------------------------------------------------------------------

class RamOptimizer:
    """Object-oriented interface for RAM optimization (wraps module functions)."""

    def optimize(self) -> dict:
        return optimize()

    def empty_process_working_sets(self) -> None:
        empty_process_working_sets()

    def flush_file_cache(self) -> None:
        flush_file_cache()

    def get_free_ram_mb(self) -> int:
        return _get_free_ram_mb()
