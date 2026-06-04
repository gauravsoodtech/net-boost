"""
Unit tests for core.nvidia_optimizer.

Patches the module-private _read_reg / _write_reg / _delete_reg seams so the
tests stay portable across machines without a real NVIDIA GPU and without
touching HKLM.
"""

from unittest.mock import MagicMock, patch

import pytest

from core import nvidia_optimizer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _patch_reg(monkeypatch, reads=None):
    """
    Stub out the registry I/O seams.  Returns (writes, deletes) lists that the
    test can assert against.

    *reads* maps (subkey, value_name) → original value to return from _read_reg.
    Unmatched lookups return None (mirrors a missing registry entry).
    """
    reads = reads or {}
    writes = []
    deletes = []

    def fake_read(hive, subkey, value_name):
        return reads.get((subkey, value_name))

    def fake_write(hive, subkey, value_name, value):
        writes.append((subkey, value_name, value))

    def fake_delete(hive, subkey, value_name):
        deletes.append((subkey, value_name))

    monkeypatch.setattr(nvidia_optimizer, "_read_reg", fake_read)
    monkeypatch.setattr(nvidia_optimizer, "_write_reg", fake_write)
    monkeypatch.setattr(nvidia_optimizer, "_delete_reg", fake_delete)
    monkeypatch.setattr(nvidia_optimizer, "is_nvidia_smi_available", lambda: False)
    monkeypatch.setattr(nvidia_optimizer, "get_gpu_registry_key", lambda: None)
    return writes, deletes


# ── apply() ───────────────────────────────────────────────────────────────────

def test_apply_dynamic_pstate_off_writes_registry(monkeypatch):
    writes, _ = _patch_reg(monkeypatch, reads={
        (nvidia_optimizer._NVTWEAK_GLOBAL_HKLM, "DisableDynamicPstate"): 0,
    })

    backup = nvidia_optimizer.apply({"dynamic_pstate_off": True})

    assert (nvidia_optimizer._NVTWEAK_GLOBAL_HKLM, "DisableDynamicPstate", 1) in writes
    assert backup["_registry"][0]["original"] == 0
    assert backup["_registry"][0]["value_name"] == "DisableDynamicPstate"


def test_apply_ull_mode_writes_software_key(monkeypatch):
    writes, _ = _patch_reg(monkeypatch)

    nvidia_optimizer.apply({"ull_mode": True})

    assert (nvidia_optimizer._NVTWEAK_SOFTWARE, "ULMDMode", 1) in writes


def test_apply_max_power_writes_powermizer_when_gpu_key_present(monkeypatch):
    writes, _ = _patch_reg(monkeypatch)
    monkeypatch.setattr(nvidia_optimizer, "get_gpu_registry_key", lambda: "GPU\\KEY")

    nvidia_optimizer.apply({"max_power": True})

    assert ("GPU\\KEY", "PowerMizerEnable", 0) in writes
    assert ("GPU\\KEY", "PowerMizerLevel", 1) in writes


def test_apply_max_power_records_failure_when_no_gpu_key(monkeypatch):
    writes, _ = _patch_reg(monkeypatch)
    # get_gpu_registry_key already returns None via _patch_reg

    backup = nvidia_optimizer.apply({"max_power": True})

    assert writes == []
    assert backup["_registry"] == []
    # Previously a silent skip; now recorded so the UI can warn the GPU tweak
    # did not apply.
    assert backup["_verify"]["failed"] == 1
    assert backup["_verify"]["failed_values"][0]["reason"] == "NVIDIA GPU registry key not found"


def test_apply_disable_hags_writes_hwschmode(monkeypatch):
    writes, _ = _patch_reg(monkeypatch)

    nvidia_optimizer.apply({"disable_hags": True})

    assert (nvidia_optimizer._GRAPHICS_DRIVERS, "HwSchMode", 1) in writes


def test_apply_empty_settings_returns_empty_backup(monkeypatch):
    writes, _ = _patch_reg(monkeypatch)

    backup = nvidia_optimizer.apply({})

    assert writes == []
    assert backup["_registry"] == []
    assert backup["_verify"]["written"] == 0
    assert backup["_verify"]["failed"] == 0


# ── apply() read-back verification ───────────────────────────────────────────

def _patch_reg_stateful(monkeypatch, initial=None):
    """Registry seam whose writes persist, so read-back verification can pass."""
    store = dict(initial or {})  # (subkey, value_name) -> value

    monkeypatch.setattr(nvidia_optimizer, "_read_reg",
                        lambda hive, subkey, vname: store.get((subkey, vname)))
    monkeypatch.setattr(nvidia_optimizer, "_write_reg",
                        lambda hive, subkey, vname, value: store.__setitem__((subkey, vname), value))
    monkeypatch.setattr(nvidia_optimizer, "_delete_reg", lambda *a: None)
    monkeypatch.setattr(nvidia_optimizer, "is_nvidia_smi_available", lambda: False)
    monkeypatch.setattr(nvidia_optimizer, "get_gpu_registry_key", lambda: None)
    return store


def test_apply_verifies_writes_that_persist(monkeypatch):
    _patch_reg_stateful(monkeypatch)

    backup = nvidia_optimizer.apply({"ull_mode": True})

    v = backup["_verify"]
    assert v["written"] == 1
    assert v["verified"] == 1
    assert v["failed"] == 0
    assert "ULMDMode" in v["verified_values"]


def test_apply_records_readback_mismatch_when_write_does_not_stick(monkeypatch):
    # Read returns the stale original; write is a no-op (does not persist).
    store = {(nvidia_optimizer._NVTWEAK_SOFTWARE, "ULMDMode"): 0}
    monkeypatch.setattr(nvidia_optimizer, "_read_reg",
                        lambda hive, subkey, vname: store.get((subkey, vname)))
    monkeypatch.setattr(nvidia_optimizer, "_write_reg", lambda *a: None)
    monkeypatch.setattr(nvidia_optimizer, "is_nvidia_smi_available", lambda: False)
    monkeypatch.setattr(nvidia_optimizer, "get_gpu_registry_key", lambda: None)

    backup = nvidia_optimizer.apply({"ull_mode": True})

    v = backup["_verify"]
    assert v["verified"] == 0
    assert v["failed"] == 1
    assert v["failed_values"][0]["reason"] == "readback mismatch"


def test_apply_records_write_failure_and_does_not_raise(monkeypatch):
    def boom(hive, subkey, vname, value):
        raise OSError("access denied")

    monkeypatch.setattr(nvidia_optimizer, "_read_reg", lambda *a: None)
    monkeypatch.setattr(nvidia_optimizer, "_write_reg", boom)
    monkeypatch.setattr(nvidia_optimizer, "is_nvidia_smi_available", lambda: False)
    monkeypatch.setattr(nvidia_optimizer, "get_gpu_registry_key", lambda: None)

    backup = nvidia_optimizer.apply({"ull_mode": True})  # must not raise

    v = backup["_verify"]
    assert v["failed"] == 1
    assert "write failed" in v["failed_values"][0]["reason"]


def test_apply_runs_nvidia_smi_persistent_mode_when_available(monkeypatch):
    _patch_reg(monkeypatch)
    monkeypatch.setattr(nvidia_optimizer, "is_nvidia_smi_available", lambda: True)
    smi_calls = []
    monkeypatch.setattr(
        nvidia_optimizer,
        "run_nvidia_smi",
        lambda args: smi_calls.append(list(args)) or "",
    )

    backup = nvidia_optimizer.apply({})

    assert smi_calls == [["-pm", "1"]]
    assert backup["_nvidia_smi_pm_applied"] is True


def test_apply_swallows_nvidia_smi_failure(monkeypatch):
    _patch_reg(monkeypatch)
    monkeypatch.setattr(nvidia_optimizer, "is_nvidia_smi_available", lambda: True)

    def boom(_args):
        raise RuntimeError("nvidia-smi not happy")

    monkeypatch.setattr(nvidia_optimizer, "run_nvidia_smi", boom)

    backup = nvidia_optimizer.apply({})  # must not raise

    assert "_nvidia_smi_pm_applied" not in backup


# ── restore() ────────────────────────────────────────────────────────────────

def test_restore_v2_round_trip_writes_originals_back(monkeypatch):
    writes, deletes = _patch_reg(monkeypatch)

    backup = {
        "_registry": [
            {"hive": "hklm", "subkey": "A", "value_name": "X", "original": 7},
            {"hive": "hklm", "subkey": "B", "value_name": "Y", "original": None},
        ]
    }

    nvidia_optimizer.restore(backup)

    assert ("A", "X", 7) in writes
    assert ("B", "Y") in deletes  # None original -> delete


def test_restore_v1_legacy_compound_keys(monkeypatch):
    writes, deletes = _patch_reg(monkeypatch)

    backup = {
        "hklm:OldSubkey:OldValue": 42,
        "hklm:OtherSubkey:Missing": None,
        "_nvidia_smi_pm_applied": False,  # private key — must be skipped
    }

    nvidia_optimizer.restore(backup)

    assert ("OldSubkey", "OldValue", 42) in writes
    assert ("OtherSubkey", "Missing") in deletes


def test_restore_disables_persistent_mode_when_flag_set(monkeypatch):
    _patch_reg(monkeypatch)
    smi_calls = []
    monkeypatch.setattr(
        nvidia_optimizer,
        "run_nvidia_smi",
        lambda args: smi_calls.append(list(args)) or "",
    )

    nvidia_optimizer.restore({"_nvidia_smi_pm_applied": True})

    assert smi_calls == [["-pm", "0"]]


# ── get_gpu_registry_key ─────────────────────────────────────────────────────

def test_get_gpu_registry_key_finds_nvidia_subkey(monkeypatch):
    fake_video = MagicMock()
    fake_video.__enter__ = lambda self: fake_video
    fake_video.__exit__ = lambda *a: None

    monkeypatch.setattr(nvidia_optimizer.winreg, "OpenKey", lambda *a, **kw: fake_video)

    enum_results = iter(["{GUID-1}", "{GUID-2}"])

    def fake_enum(_handle, _idx):
        try:
            return next(enum_results)
        except StopIteration:
            raise OSError("end")

    monkeypatch.setattr(nvidia_optimizer.winreg, "EnumKey", fake_enum)

    reads = {
        ("SYSTEM\\CurrentControlSet\\Control\\Video\\{GUID-1}\\0000", "Device Description"): None,
        ("SYSTEM\\CurrentControlSet\\Control\\Video\\{GUID-1}\\0000", "DriverDesc"): "Intel HD Graphics",
        ("SYSTEM\\CurrentControlSet\\Control\\Video\\{GUID-2}\\0000", "Device Description"): "NVIDIA RTX 4060",
    }
    monkeypatch.setattr(
        nvidia_optimizer,
        "_read_reg",
        lambda hive, subkey, value: reads.get((subkey, value)),
    )

    found = nvidia_optimizer.get_gpu_registry_key()
    assert found == "SYSTEM\\CurrentControlSet\\Control\\Video\\{GUID-2}\\0000"


def test_get_gpu_registry_key_returns_none_when_no_nvidia(monkeypatch):
    fake_video = MagicMock()
    fake_video.__enter__ = lambda self: fake_video
    fake_video.__exit__ = lambda *a: None

    monkeypatch.setattr(nvidia_optimizer.winreg, "OpenKey", lambda *a, **kw: fake_video)

    def fake_enum(_handle, _idx):
        raise OSError("end")

    monkeypatch.setattr(nvidia_optimizer.winreg, "EnumKey", fake_enum)
    monkeypatch.setattr(nvidia_optimizer, "_read_reg", lambda *a, **kw: None)

    assert nvidia_optimizer.get_gpu_registry_key() is None


def test_get_gpu_registry_key_returns_none_when_video_key_missing(monkeypatch):
    def boom(*a, **kw):
        raise OSError("video key missing")

    monkeypatch.setattr(nvidia_optimizer.winreg, "OpenKey", boom)

    assert nvidia_optimizer.get_gpu_registry_key() is None


# ── nvidia-smi discovery ─────────────────────────────────────────────────────

def test_is_nvidia_smi_available_known_path(monkeypatch):
    monkeypatch.setattr(
        nvidia_optimizer.os.path,
        "isfile",
        lambda p: p == nvidia_optimizer._NVIDIA_SMI_PATHS[0],
    )
    assert nvidia_optimizer.is_nvidia_smi_available() is True


def test_is_nvidia_smi_available_falls_back_to_path_lookup(monkeypatch):
    monkeypatch.setattr(nvidia_optimizer.os.path, "isfile", lambda p: False)
    with patch("shutil.which", return_value=r"C:\custom\nvidia-smi.exe"):
        assert nvidia_optimizer.is_nvidia_smi_available() is True


def test_is_nvidia_smi_available_returns_false_when_missing(monkeypatch):
    monkeypatch.setattr(nvidia_optimizer.os.path, "isfile", lambda p: False)
    with patch("shutil.which", return_value=None):
        assert nvidia_optimizer.is_nvidia_smi_available() is False


def test_find_nvidia_smi_raises_when_missing(monkeypatch):
    monkeypatch.setattr(nvidia_optimizer.os.path, "isfile", lambda p: False)
    with patch("shutil.which", return_value=None):
        with pytest.raises(FileNotFoundError):
            nvidia_optimizer._find_nvidia_smi()
