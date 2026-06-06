"""
Tests for the CS2-specific MainWindow Game Mode wiring.

CS2 is monitoring-only by default. It must not auto-apply Wi-Fi registry
tweaks, FPS Booster settings, Optimizer settings, or per-app DSCP QoS.

The MainWindow still carries the DSCP teardown machinery as defensive cleanup,
so the deactivate tests below set a policy directly to exercise it.
"""

from unittest.mock import MagicMock, patch

import pytest

from ui.main_window import MainWindow

# Reuse the test fixtures from the Valorant suite - duplicated dummies would
# drift over time.
from tests.test_main_window_game_mode import _window_for_game_mode


@pytest.fixture
def cs2_window():
    window = _window_for_game_mode()
    window.state_guard = MagicMock()
    window._current_game_pid = 4242
    window._game_mode_dscp_policy = None
    return window


def test_cs2_game_mode_does_not_apply_wifi(cs2_window):
    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    cs2_window._apply_wifi.assert_not_called()
    assert cs2_window._applied_settings == {}
    assert cs2_window._game_mode_applied is False


def test_cs2_game_mode_does_not_mutate_wifi_toggles_or_badges(cs2_window):
    pre_game = cs2_window.tab_wifi.get_settings()

    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    assert cs2_window.tab_wifi.get_settings() == pre_game
    assert cs2_window.tab_wifi.marked is None
    assert cs2_window._pre_game_mode_settings is None


def test_cs2_deactivate_has_no_wifi_snapshot_to_restore(cs2_window):
    pre_game = cs2_window.tab_wifi.get_settings()
    cs2_window._game_mode_active = True

    MainWindow._activate_game_mode(cs2_window, "cs2.exe")
    MainWindow._deactivate_game_mode(cs2_window)

    assert cs2_window.tab_wifi.get_settings() == pre_game
    assert cs2_window.tab_wifi.marked is None
    assert cs2_window._applied_settings == {}
    assert cs2_window._pre_game_mode_settings is None


def test_cs2_game_mode_does_not_apply_fps_or_optimizer(cs2_window):
    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    cs2_window._apply_fps.assert_not_called()
    cs2_window._apply_optimizer.assert_not_called()


def test_cs2_game_mode_does_not_create_dscp_policy(cs2_window):
    with patch("core.bandwidth_manager.apply_dscp_policy") as apply_dscp:
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    apply_dscp.assert_not_called()
    cs2_window.state_guard.add_qos_policy.assert_not_called()
    assert cs2_window._game_mode_dscp_policy is None
    assert cs2_window._game_mode_applied is False


def test_cs2_game_mode_does_not_start_gpu_temp_timer(cs2_window):
    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    assert cs2_window._gpu_temp_timer.started is False


def test_cs2_game_mode_does_not_populate_monitor_settings(cs2_window):
    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    assert cs2_window._applied_settings == {}
    assert cs2_window.tab_monitor.applied is None
    assert cs2_window._game_mode_dscp_policy is None


def test_valorant_game_mode_stays_monitoring_only(cs2_window):
    with patch("core.bandwidth_manager.apply_dscp_policy") as apply_dscp:
        MainWindow._activate_game_mode(cs2_window, "VALORANT-Win64-Shipping.exe")

    apply_dscp.assert_not_called()
    cs2_window.state_guard.add_qos_policy.assert_not_called()
    assert cs2_window._game_mode_dscp_policy is None
    cs2_window._apply_wifi.assert_not_called()
    cs2_window._apply_fps.assert_not_called()
    cs2_window._apply_optimizer.assert_not_called()
    assert cs2_window._game_mode_applied is False


def test_deactivate_game_mode_removes_dscp_policy(cs2_window):
    cs2_window._game_mode_dscp_policy = "NetBoost_cs2_foo"
    cs2_window._game_mode_applied = True

    with patch("core.bandwidth_manager.remove_dscp_policy") as remove_dscp:
        MainWindow._deactivate_game_mode(cs2_window)

    remove_dscp.assert_called_once_with("NetBoost_cs2_foo")
    assert cs2_window._game_mode_dscp_policy is None


def test_deactivate_removes_dscp_even_when_other_sections_failed(cs2_window):
    cs2_window._game_mode_dscp_policy = "NetBoost_cs2_x"
    cs2_window._game_mode_applied = False

    with patch("core.bandwidth_manager.remove_dscp_policy") as remove_dscp:
        MainWindow._deactivate_game_mode(cs2_window)

    remove_dscp.assert_called_once_with("NetBoost_cs2_x")
    assert cs2_window._game_mode_dscp_policy is None


def test_cs2_monitoring_only_toast_uses_cs2_label(cs2_window):
    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    assert cs2_window._toast.messages[-1] == (
        "CS2 Game Mode monitoring only - Wi-Fi tweaks are manual",
        "info",
        None,
    )
    cs2_window._set_status.assert_any_call(
        "CS2 Game Mode monitoring only - no Wi-Fi changes applied"
    )
