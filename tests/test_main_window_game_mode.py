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


class _DummyDashboard:
    def __init__(self):
        self.detected_game = None
        self.game_mode = None

    def set_game_detected(self, name):
        self.detected_game = name

    def set_game_mode(self, enabled):
        self.game_mode = enabled


class _DummyRoute:
    def __init__(self):
        self.detected = None

    def on_game_detected(self, exe_name, pid):
        self.detected = (exe_name, pid)

    def on_game_exited(self):
        self.detected = None


class _DummyWatcher:
    def __init__(self, running_games):
        self._running_games = list(running_games)

    def get_running_games(self):
        return list(self._running_games)


def _window_for_game_mode():
    window = MainWindow.__new__(MainWindow)
    window.state_guard = None
    window._applied_settings = {}
    window._game_mode_applied = False
    window._game_mode_active = False
    window._game_mode_pending = False
    window._current_game = None
    window._current_game_pid = 0
    window.process_watcher = None
    window.tray = None
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
    window.tab_dashboard = _DummyDashboard()
    window.tab_route = _DummyRoute()

    window._apply_wifi = MagicMock(return_value={
        "_adapter_found": True,
        "_write_count": 6,
        "_verified_count": 6,
        "_failed_count": 0,
        "_failed_values": [],
    })
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


def test_valorant_game_mode_does_not_mark_applied_when_wifi_adapter_missing():
    window = _window_for_game_mode()
    window._apply_wifi.return_value = {
        "_adapter_found": False,
        "_write_count": 0,
        "_verified_count": 0,
        "_failed_count": 0,
        "_failed_values": [],
    }

    MainWindow._activate_game_mode(window, "VALORANT-Win64-Shipping.exe")

    assert window._game_mode_applied is False
    assert window._applied_settings == {}
    assert window.tab_wifi.marked is None
    assert window.tab_monitor.applied == {}
    assert window._toast.messages[-1][1] == "warning"
    window._set_status.assert_any_call(
        "Game Mode: Wi-Fi failed: Wi-Fi adapter key not found - LSO may still be active. "
        "Run as admin and confirm the adapter is supported."
    )


def test_valorant_game_mode_does_not_mark_applied_when_no_wifi_write_confirmed():
    window = _window_for_game_mode()
    window._apply_wifi.return_value = {
        "_adapter_found": True,
        "_write_count": 2,
        "_verified_count": 0,
        "_failed_count": 2,
        "_failed_values": [
            {"name": "*LsoV2IPv4", "reason": "readback mismatch"},
            {"name": "*LsoV2IPv6", "reason": "readback mismatch"},
        ],
    }

    MainWindow._activate_game_mode(window, "VALORANT-Win64-Shipping.exe")

    assert window._game_mode_applied is False
    assert window._applied_settings == {}
    assert window.tab_wifi.marked is None
    assert window._toast.messages[-1][1] == "warning"


def test_valorant_game_mode_marks_partial_wifi_apply_as_warning():
    window = _window_for_game_mode()
    window._apply_wifi.return_value = {
        "_adapter_found": True,
        "_write_count": 2,
        "_verified_count": 1,
        "_failed_count": 1,
        "_failed_values": [{"name": "*LsoV2IPv6", "reason": "readback mismatch"}],
    }

    MainWindow._activate_game_mode(window, "VALORANT-Win64-Shipping.exe")

    assert window._game_mode_applied is True
    assert "wifi" in window._applied_settings
    assert window.tab_wifi.marked == window._applied_settings["wifi"]
    assert window._toast.messages[-1] == (
        "Wi-Fi partially applied: 1/2 values confirmed.",
        "warning",
        None,
    )


def test_game_mode_toggle_applies_when_valorant_already_running():
    window = _window_for_game_mode()
    window.process_watcher = _DummyWatcher(["valorant-win64-shipping.exe"])
    window._game_mode_pending = True

    MainWindow._apply_game_mode_toggle(window)

    assert window._game_mode_active is True
    assert window._current_game == "valorant-win64-shipping.exe"
    assert window.tab_dashboard.detected_game == "valorant-win64-shipping.exe"
    assert window.tab_route.detected[0] == "valorant-win64-shipping.exe"
    window._apply_wifi.assert_called_once()
    assert window._game_mode_applied is True
