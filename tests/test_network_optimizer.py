"""
Unit tests for core.network_optimizer.

Patches the module-private _read_reg / _write_reg / _delete_reg / get_interface_guids
seams so the suite stays portable and never touches HKLM.
"""

import winreg

import pytest

from core import network_optimizer


# ── Helpers ───────────────────────────────────────────────────────────────────

def _stub_io(monkeypatch, reads=None, guids=None):
    """
    Replace the registry I/O seams.  Returns (writes, deletes) lists for assertion.

    *reads* maps (key_path, value_name) → (value, type) tuple or None.
    *guids* maps adapter_name → registry subkey path; defaults to a single
    Wi-Fi adapter so apply() does work.
    """
    reads = reads or {}
    guids = guids if guids is not None else {
        "Wi-Fi": f"{network_optimizer.TCP_PARAMS_BASE}\\{{IFACE-1}}",
    }
    writes = []
    deletes = []

    def fake_read(key_path, value_name):
        return reads.get((key_path, value_name))

    def fake_write(key_path, value_name, value, value_type=winreg.REG_DWORD):
        writes.append((key_path, value_name, value, value_type))

    def fake_delete(key_path, value_name):
        deletes.append((key_path, value_name))

    monkeypatch.setattr(network_optimizer, "_read_reg", fake_read)
    monkeypatch.setattr(network_optimizer, "_write_reg", fake_write)
    monkeypatch.setattr(network_optimizer, "_delete_reg", fake_delete)
    monkeypatch.setattr(network_optimizer, "get_interface_guids", lambda: dict(guids))
    return writes, deletes


# ── apply() ──────────────────────────────────────────────────────────────────

def test_apply_writes_per_interface_tcp_no_delay_and_ack_freq(monkeypatch):
    iface_path = f"{network_optimizer.TCP_PARAMS_BASE}\\{{IFACE-1}}"
    writes, _ = _stub_io(monkeypatch, reads={
        (iface_path, "TcpAckFrequency"): (0, winreg.REG_DWORD),
        (iface_path, "TCPNoDelay"): None,
    })

    backup = network_optimizer.apply({"tcp_ack_freq": True, "tcp_no_delay": True})

    assert (iface_path, "TcpAckFrequency", 1, winreg.REG_DWORD) in writes
    assert (iface_path, "TCPNoDelay", 1, winreg.REG_DWORD) in writes
    assert backup["interfaces"]["Wi-Fi"]["TcpAckFrequency"] == (0, winreg.REG_DWORD)
    assert backup["interfaces"]["Wi-Fi"]["TCPNoDelay"] is None


def test_apply_window_scaling_writes_tcp1323opts_1_not_3(monkeypatch):
    """Pitfall guard: Tcp1323Opts must be 1 (window scaling only), never 3."""
    writes, _ = _stub_io(monkeypatch)

    network_optimizer.apply({"window_scaling": True})

    tcp1323 = [w for w in writes if w[1] == "Tcp1323Opts"]
    assert tcp1323, "Expected Tcp1323Opts to be written"
    for _path, _name, value, _type in tcp1323:
        assert value == 1, f"Tcp1323Opts must be 1, not {value}"

    global_writes = [w for w in writes if w[1] == "GlobalMaxTcpWindowSize"]
    assert global_writes
    for _path, _name, value, _type in global_writes:
        assert value == 65535


def test_apply_writes_per_each_interface_when_multiple(monkeypatch):
    guids = {
        "Wi-Fi": f"{network_optimizer.TCP_PARAMS_BASE}\\{{IFACE-A}}",
        "Ethernet": f"{network_optimizer.TCP_PARAMS_BASE}\\{{IFACE-B}}",
    }
    writes, _ = _stub_io(monkeypatch, guids=guids)

    network_optimizer.apply({"tcp_no_delay": True})

    written_paths = {w[0] for w in writes if w[1] == "TCPNoDelay"}
    assert written_paths == set(guids.values())


def test_apply_empty_settings_returns_empty_per_interface_backup(monkeypatch):
    writes, _ = _stub_io(monkeypatch)

    backup = network_optimizer.apply({})

    assert writes == []
    # The optimiser still records the interface entries, just with empty dicts.
    assert backup["interfaces"]["Wi-Fi"] == {}
    assert backup["global"] == {}


def test_apply_returns_early_when_no_interface_guids(monkeypatch):
    writes, _ = _stub_io(monkeypatch, guids={})

    backup = network_optimizer.apply({"tcp_no_delay": True, "window_scaling": True})

    assert writes == []
    assert backup == {"interfaces": {}, "global": {}}


# ── restore() ────────────────────────────────────────────────────────────────

def test_restore_writes_originals_back_and_deletes_missing(monkeypatch):
    iface_path = f"{network_optimizer.TCP_PARAMS_BASE}\\{{IFACE-1}}"
    writes, deletes = _stub_io(monkeypatch)

    backup = {
        "interfaces": {
            "Wi-Fi": {
                "TcpAckFrequency": (0, winreg.REG_DWORD),
                "TCPNoDelay": None,  # was absent — must be deleted on restore
            }
        },
        "global": {
            "Tcp1323Opts": (3, winreg.REG_DWORD),  # original was 3 (timestamps)
            "GlobalMaxTcpWindowSize": None,
        },
    }

    network_optimizer.restore(backup)

    assert (iface_path, "TcpAckFrequency", 0, winreg.REG_DWORD) in writes
    assert (iface_path, "TCPNoDelay") in deletes
    assert (network_optimizer._GLOBAL_KEY, "Tcp1323Opts", 3, winreg.REG_DWORD) in writes
    assert (network_optimizer._GLOBAL_KEY, "GlobalMaxTcpWindowSize") in deletes


def test_restore_skips_adapter_not_currently_present(monkeypatch):
    writes, deletes = _stub_io(monkeypatch, guids={})

    backup = {
        "interfaces": {"GoneAdapter": {"TcpAckFrequency": (0, winreg.REG_DWORD)}},
        "global": {},
    }

    network_optimizer.restore(backup)

    assert writes == []
    assert deletes == []


def test_restore_value_skips_unexpected_format(monkeypatch):
    iface_path = f"{network_optimizer.TCP_PARAMS_BASE}\\{{IFACE-1}}"
    writes, deletes = _stub_io(monkeypatch)

    # original is a bare int instead of (value, type) — must be skipped, not crash
    network_optimizer._restore_value(iface_path, "TcpAckFrequency", 42)

    assert writes == []
    assert deletes == []


# ── NetworkOptimizer class wrapper ───────────────────────────────────────────

def test_class_wrapper_delegates_to_module_functions(monkeypatch):
    writes, _ = _stub_io(monkeypatch)

    opt = network_optimizer.NetworkOptimizer()

    assert opt.get_interface_guids() == {
        "Wi-Fi": f"{network_optimizer.TCP_PARAMS_BASE}\\{{IFACE-1}}",
    }

    backup = opt.apply({"tcp_no_delay": True})
    assert any(w[1] == "TCPNoDelay" for w in writes)

    opt.restore(backup)  # round-trip — must not raise
