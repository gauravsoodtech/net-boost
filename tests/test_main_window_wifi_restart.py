"""
Tests for the Wi-Fi adapter-restart trigger in MainWindow.

A raw registry write does not take effect until the Intel miniport driver
re-reads its config (a power-cycle).  MainWindow must restart the adapter after
a Wi-Fi apply that actually changed a value — and must NOT restart when nothing
changed (avoids a needless ~5-10 s Wi-Fi drop).
"""

from unittest.mock import MagicMock

import ui.main_window as mw
from ui.main_window import MainWindow

from tests.test_main_window_game_mode import _window_for_game_mode


class _FakePool:
    """Stand-in for QThreadPool.globalInstance() that records started workers
    without ever running them (so restart_adapter / subprocess never fires)."""
    started = []

    @classmethod
    def globalInstance(cls):
        return cls

    @classmethod
    def start(cls, worker):
        cls.started.append(worker)


def _restart_window(monkeypatch):
    window = _window_for_game_mode()
    window._wifi_restart_signals = MagicMock()
    _FakePool.started = []
    monkeypatch.setattr(mw, "QThreadPool", _FakePool)
    return window


def test_maybe_restart_spawns_worker_when_value_changed(monkeypatch):
    window = _restart_window(monkeypatch)
    backup = {
        "_requires_restart": True,
        "_adapter_found": True,
        "_driver_desc": "Intel(R) Wi-Fi 6E AX211 160MHz",
    }

    MainWindow._maybe_restart_wifi_adapter(window, backup)

    assert len(_FakePool.started) == 1
    assert _FakePool.started[0].driver_desc == "Intel(R) Wi-Fi 6E AX211 160MHz"
    assert any("restarting" in m.lower() for m, _lvl, _dur in window._toast.messages)


def test_maybe_restart_skips_when_nothing_changed(monkeypatch):
    window = _restart_window(monkeypatch)

    MainWindow._maybe_restart_wifi_adapter(window, {"_requires_restart": False})

    assert _FakePool.started == []
    assert window._toast.messages == []


def test_maybe_restart_skips_when_adapter_missing(monkeypatch):
    window = _restart_window(monkeypatch)
    backup = {"_requires_restart": True, "_adapter_found": False}

    MainWindow._maybe_restart_wifi_adapter(window, backup)

    assert _FakePool.started == []


def test_maybe_restart_skips_on_plain_apply_backup(monkeypatch):
    """The default _apply_wifi mock returns a dict with no _requires_restart
    key — the guard must treat that as 'no restart'."""
    window = _restart_window(monkeypatch)
    backup = {"_adapter_found": True, "_write_count": 6, "_verified_count": 6}

    MainWindow._maybe_restart_wifi_adapter(window, backup)

    assert _FakePool.started == []


def test_on_wifi_restart_done_success_toast():
    window = _window_for_game_mode()

    MainWindow._on_wifi_restart_done(window, True, "")

    success = [m for m, lvl, _ in window._toast.messages if lvl == "success"]
    assert any("live" in m.lower() for m in success)


def test_on_wifi_restart_done_failure_toast():
    window = _window_for_game_mode()

    MainWindow._on_wifi_restart_done(window, False, "Access denied")

    warnings = [m for m, lvl, _ in window._toast.messages if lvl == "warning"]
    assert any("Device Manager" in m for m in warnings)


def test_wifi_restore_restarts_adapter_when_restored_values_need_reset(monkeypatch):
    window = _restart_window(monkeypatch)
    backup = {
        "_requires_restart": True,
        "_adapter_found": True,
        "_driver_desc": "Intel AX211",
        "_adapter_key": "adapter-key",
        "PowerSavingMode": 1,
    }
    window._wifi_optimizer = MagicMock()
    window.state_guard = MagicMock()
    window.state_guard.get_state.return_value = {"wifi_backup": backup}

    MainWindow._on_wifi_restore(window)

    window._wifi_optimizer.restore.assert_called_once_with(dict(backup))
    assert len(_FakePool.started) == 1
    assert _FakePool.started[0].driver_desc == "Intel AX211"


def test_wifi_restore_skips_restart_when_backup_did_not_change_driver_values(monkeypatch):
    window = _restart_window(monkeypatch)
    backup = {
        "_requires_restart": False,
        "_adapter_found": True,
        "_driver_desc": "Intel AX211",
        "PowerSavingMode": 0,
    }
    window._wifi_optimizer = MagicMock()
    window.state_guard = MagicMock()
    window.state_guard.get_state.return_value = {"wifi_backup": backup}

    MainWindow._on_wifi_restore(window)

    window._wifi_optimizer.restore.assert_called_once_with(dict(backup))
    assert _FakePool.started == []
