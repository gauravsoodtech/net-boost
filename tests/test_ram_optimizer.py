"""
Unit tests for core.ram_optimizer.

Patches psutil and ctypes.windll.kernel32 so the suite runs everywhere
without touching real process working sets or the file cache.
"""

import os
from unittest.mock import MagicMock

import pytest

from core import ram_optimizer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stub_psutil(monkeypatch, processes=None, virtual_memory_available=512 * 1024 * 1024):
    """
    Replace psutil.process_iter and psutil.virtual_memory with mocks.
    *processes* is a list of (pid, name) pairs.
    """
    processes = processes or []

    def fake_process_iter(_attrs):
        for pid, name in processes:
            p = MagicMock()
            p.info = {"name": name, "pid": pid}
            yield p

    fake_vmem = MagicMock()
    fake_vmem.available = virtual_memory_available

    monkeypatch.setattr(ram_optimizer.psutil, "process_iter", fake_process_iter)
    monkeypatch.setattr(ram_optimizer.psutil, "virtual_memory", lambda: fake_vmem)


def _stub_kernel32(monkeypatch, open_handle=0xDEADBEEF, set_cache_success=True):
    """
    Replace ctypes.windll.kernel32 with a MagicMock and record calls.
    Returns the fake kernel32 object so tests can introspect call_args.
    """
    fake = MagicMock()
    fake.OpenProcess.return_value = open_handle
    fake.K32EmptyWorkingSet.return_value = 1   # success
    fake.EmptyWorkingSet.return_value = 1
    fake.CloseHandle.return_value = True
    fake.SetSystemFileCacheSize.return_value = 1 if set_cache_success else 0
    fake.GetLastError.return_value = 1314      # ERROR_PRIVILEGE_NOT_HELD example

    monkeypatch.setattr(ram_optimizer.ctypes.windll, "kernel32", fake, raising=False)
    return fake


# ── _get_free_ram_mb ─────────────────────────────────────────────────────────

def test_get_free_ram_mb_converts_bytes_to_mib(monkeypatch):
    _stub_psutil(monkeypatch, virtual_memory_available=2 * 1024 * 1024 * 1024)  # 2 GiB
    assert ram_optimizer._get_free_ram_mb() == 2048


# ── empty_process_working_sets ───────────────────────────────────────────────

def test_empty_process_working_sets_skips_critical_processes(monkeypatch):
    own_pid = os.getpid()
    _stub_psutil(monkeypatch, processes=[
        (own_pid, "python.exe"),     # self — skip
        (4,       "System"),          # critical — skip
        (1000,    "lsass.exe"),       # critical — skip
        (2000,    "chrome.exe"),      # ok
    ])
    fake = _stub_kernel32(monkeypatch)

    ram_optimizer.empty_process_working_sets()

    open_pids = [c.args[2] for c in fake.OpenProcess.call_args_list]
    assert own_pid not in open_pids
    assert 4 not in open_pids
    assert 1000 not in open_pids
    assert 2000 in open_pids
    assert fake.CloseHandle.called


def test_empty_process_working_sets_skips_unopenable_processes(monkeypatch):
    _stub_psutil(monkeypatch, processes=[(2000, "chrome.exe")])
    fake = _stub_kernel32(monkeypatch, open_handle=0)  # OpenProcess returns NULL

    ram_optimizer.empty_process_working_sets()

    fake.OpenProcess.assert_called_once()
    fake.K32EmptyWorkingSet.assert_not_called()
    fake.EmptyWorkingSet.assert_not_called()
    fake.CloseHandle.assert_not_called()


def test_empty_process_working_sets_falls_back_to_legacy_export(monkeypatch):
    _stub_psutil(monkeypatch, processes=[(2000, "chrome.exe")])
    fake = _stub_kernel32(monkeypatch)
    fake.K32EmptyWorkingSet.return_value = 0  # K32 variant fails -> legacy fallback

    ram_optimizer.empty_process_working_sets()

    fake.K32EmptyWorkingSet.assert_called_once()
    fake.EmptyWorkingSet.assert_called_once()
    fake.CloseHandle.assert_called_once()


def test_empty_process_working_sets_swallows_per_process_no_such_process(monkeypatch):
    import psutil as real_psutil

    def fake_iter(_attrs):
        bad = MagicMock()
        type(bad).info = property(lambda self: (_ for _ in ()).throw(real_psutil.NoSuchProcess(1)))
        good = MagicMock()
        good.info = {"name": "chrome.exe", "pid": 2000}
        yield bad
        yield good

    monkeypatch.setattr(ram_optimizer.psutil, "process_iter", fake_iter)
    fake = _stub_kernel32(monkeypatch)

    ram_optimizer.empty_process_working_sets()  # must not raise

    # Good process still trimmed.
    assert any(c.args[2] == 2000 for c in fake.OpenProcess.call_args_list)


# ── flush_file_cache ─────────────────────────────────────────────────────────

def test_flush_file_cache_calls_setsystemfilecachesize_with_zero_zero_flag(monkeypatch):
    fake = _stub_kernel32(monkeypatch)

    ram_optimizer.flush_file_cache()

    fake.SetSystemFileCacheSize.assert_called_once_with(0, 0, ram_optimizer._SET_CACHE_FLAGS)


def test_flush_file_cache_logs_warning_on_failure(monkeypatch, caplog):
    fake = _stub_kernel32(monkeypatch, set_cache_success=False)

    with caplog.at_level("WARNING", logger="core.ram_optimizer"):
        ram_optimizer.flush_file_cache()

    assert any("SetSystemFileCacheSize failed" in r.message for r in caplog.records)
    fake.GetLastError.assert_called_once()


# ── optimize() ───────────────────────────────────────────────────────────────

def test_optimize_returns_before_after_freed_dict(monkeypatch):
    # Two virtual_memory calls: 1024 MiB before, 1280 MiB after.
    available_values = iter([1024 * 1024 * 1024, 1280 * 1024 * 1024])

    def fake_vmem():
        v = MagicMock()
        v.available = next(available_values)
        return v

    monkeypatch.setattr(ram_optimizer.psutil, "virtual_memory", fake_vmem)
    monkeypatch.setattr(ram_optimizer.psutil, "process_iter", lambda _attrs: iter([]))
    _stub_kernel32(monkeypatch)

    result = ram_optimizer.optimize()

    assert result == {"before_mb": 1024, "after_mb": 1280, "freed_mb": 256}


def test_optimize_handles_negative_freed_when_os_reallocates(monkeypatch):
    available_values = iter([1024 * 1024 * 1024, 900 * 1024 * 1024])

    def fake_vmem():
        v = MagicMock()
        v.available = next(available_values)
        return v

    monkeypatch.setattr(ram_optimizer.psutil, "virtual_memory", fake_vmem)
    monkeypatch.setattr(ram_optimizer.psutil, "process_iter", lambda _attrs: iter([]))
    _stub_kernel32(monkeypatch, set_cache_success=False)

    result = ram_optimizer.optimize()

    assert result["freed_mb"] == -124
    assert result["before_mb"] > result["after_mb"]


# ── RamOptimizer class wrapper ───────────────────────────────────────────────

def test_class_wrapper_delegates_to_module_functions(monkeypatch):
    _stub_psutil(monkeypatch, virtual_memory_available=512 * 1024 * 1024)
    _stub_kernel32(monkeypatch)

    opt = ram_optimizer.RamOptimizer()

    assert opt.get_free_ram_mb() == 512
    opt.empty_process_working_sets()  # must not raise
    opt.flush_file_cache()             # must not raise
    result = opt.optimize()
    assert set(result.keys()) == {"before_mb", "after_mb", "freed_mb"}
