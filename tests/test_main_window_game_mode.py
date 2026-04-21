"""
Tests for MainWindow Game Mode policy selection.
"""

from unittest.mock import MagicMock

from ui.main_window import MainWindow


class _DummyTab:
    def __init__(self, settings):
        self._settings = dict(settings)
        self.marked = None

    def get_settings(self):
        return dict(self._settings)

    def mark_applied(self, settings):
        self.marked = dict(settings)


class _DummyMonitor:
    def __init__(self):
        self.applied = None

    def update_applied_settings(self, applied):
        self.applied = {
            tab: dict(settings)
            for tab, settings in applied.items()
        }


class _DummyToast:
    def __init__(self):
        self.messages = []

    def show_message(self, message, level, duration_ms=None):
        self.messages.append((message, level, duration_ms))


class _DummyTimer:
    def __init__(self):
        self.started = False

    def start(self):
        self.started = True


def _window_for_game_mode():
    window = MainWindow.__new__(MainWindow)
    window.state_guard = None
    window._applied_settings = {}
    window._game_mode_applied = False
    window._gpu_temp_timer = _DummyTimer()
    window._toast = _DummyToast()
    window._set_status = MagicMock()

    window.tab_wifi = _DummyTab({
        "disable_lso": True,
        "disable_interrupt_mod": True,
        "disable_power_saving": True,
        "minimize_roaming": True,
        "prefer_6ghz": True,
        "max_tx_power": True,
        "disable_bss_scan": True,
        "throughput_booster": True,
        "disable_mimo_power_save": True,
    })
    window.tab_fps = _DummyTab({
        "power_plan": True,
        "nvidia_max_perf": True,
        "nvidia_ull": True,
    })
    window.tab_optimizer = _DummyTab({
        "tcp_no_delay": True,
        "tcp_ack_freq": True,
        "tcp_window_scale": True,
        "switch_dns": True,
        "pause_windows_update": True,
        "pause_onedrive": True,
        "pause_bits": True,
        "pause_telemetry": True,
    })
    window.tab_monitor = _DummyMonitor()

    window._apply_wifi = MagicMock(return_value={"_adapter_found": True})
    window._apply_fps = MagicMock()
    window._apply_optimizer = MagicMock()
    return window


def test_valorant_game_mode_applies_only_stable_ping_wifi_bundle():
    from core.stable_ping_policy import stable_ping_wifi_settings

    window = _window_for_game_mode()

    MainWindow._activate_game_mode(window, "VALORANT-Win64-Shipping.exe")

    stable_wifi = stable_ping_wifi_settings()
    window._apply_wifi.assert_called_once_with(stable_wifi)
    window._apply_fps.assert_not_called()
    window._apply_optimizer.assert_not_called()
    assert window._applied_settings == {"wifi": stable_wifi}
    assert window.tab_wifi.marked == stable_wifi
    assert window.tab_monitor.applied == {"wifi": stable_wifi}
    assert window._gpu_temp_timer.started is False


def test_game_mode_without_running_game_does_not_apply_tab_settings():
    window = _window_for_game_mode()

    MainWindow._activate_game_mode(window, None)

    window._apply_wifi.assert_not_called()
    window._apply_fps.assert_not_called()
    window._apply_optimizer.assert_not_called()
    assert window._applied_settings == {}
    assert window._game_mode_applied is False
