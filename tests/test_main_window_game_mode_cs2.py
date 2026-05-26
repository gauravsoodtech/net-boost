"""
Tests for the CS2-specific MainWindow Game Mode wiring.

CS2 reuses the Valorant stable-ping Wi-Fi subset and additionally applies a
per-app DSCP EF (46) QoS policy via the bandwidth_manager.  Valorant must
never enter the DSCP path.
"""

from unittest.mock import MagicMock, patch

import pytest

from ui.main_window import MainWindow

# Reuse the test fixtures from the Valorant suite — duplicated dummies would
# drift over time.
from tests.test_main_window_game_mode import _window_for_game_mode


@pytest.fixture
def cs2_window():
    window = _window_for_game_mode()
    # CS2 path requires a non-None state_guard so add_qos_policy is exercised.
    window.state_guard = MagicMock()
    window._current_game_pid = 4242
    window._game_mode_dscp_policy = None
    return window


def test_cs2_game_mode_applies_wifi_and_dscp(cs2_window):
    from core.stable_ping_policy import stable_ping_wifi_settings

    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=True) as apply_dscp, \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_deadbeef"):
        proc_cls.return_value.exe.return_value = r"C:\Steam\cs2\bin\cs2.exe"

        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    cs2_window._apply_wifi.assert_called_once_with(stable_ping_wifi_settings())
    apply_dscp.assert_called_once_with(
        "NetBoost_cs2_deadbeef", r"C:\Steam\cs2\bin\cs2.exe", 46
    )
    cs2_window.state_guard.add_qos_policy.assert_called_once_with("NetBoost_cs2_deadbeef")
    assert cs2_window._game_mode_dscp_policy == "NetBoost_cs2_deadbeef"
    assert cs2_window._game_mode_applied is True


def test_cs2_game_mode_skips_dscp_when_pid_unknown(cs2_window):
    cs2_window._current_game_pid = 0

    with patch("core.bandwidth_manager.apply_dscp_policy") as apply_dscp:
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    apply_dscp.assert_not_called()
    assert cs2_window._game_mode_dscp_policy is None
    # Wi-Fi still applied so game mode is still considered active.
    assert cs2_window._game_mode_applied is True


def test_cs2_game_mode_skips_dscp_when_exe_path_unavailable(cs2_window):
    import psutil

    with patch("psutil.Process", side_effect=psutil.NoSuchProcess(4242)), \
         patch("core.bandwidth_manager.apply_dscp_policy") as apply_dscp:
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    apply_dscp.assert_not_called()
    assert cs2_window._game_mode_dscp_policy is None


def test_cs2_dscp_apply_failure_does_not_break_wifi(cs2_window):
    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=False), \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_x"):
        proc_cls.return_value.exe.return_value = r"C:\cs2.exe"

        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    # Wi-Fi still applied; DSCP did not stick so policy is not tracked.
    assert cs2_window._game_mode_dscp_policy is None
    assert cs2_window._game_mode_applied is True   # Wi-Fi succeeded
    # state_guard records BEFORE the apply attempt for crash-safety,
    # so we expect the call to have happened.
    cs2_window.state_guard.add_qos_policy.assert_called_once()


def test_valorant_game_mode_never_calls_dscp(cs2_window):
    with patch("core.bandwidth_manager.apply_dscp_policy") as apply_dscp:
        MainWindow._activate_game_mode(cs2_window, "VALORANT-Win64-Shipping.exe")

    apply_dscp.assert_not_called()
    cs2_window.state_guard.add_qos_policy.assert_not_called()
    assert cs2_window._game_mode_dscp_policy is None


def test_deactivate_game_mode_removes_dscp_policy(cs2_window):
    cs2_window._game_mode_dscp_policy = "NetBoost_cs2_foo"
    cs2_window._game_mode_applied = True

    with patch("core.bandwidth_manager.remove_dscp_policy") as remove_dscp:
        MainWindow._deactivate_game_mode(cs2_window)

    remove_dscp.assert_called_once_with("NetBoost_cs2_foo")
    assert cs2_window._game_mode_dscp_policy is None


def test_deactivate_removes_dscp_even_when_wifi_never_applied(cs2_window):
    """Edge case: DSCP succeeded but Wi-Fi failed. _game_mode_applied is False
    but the DSCP policy must still come down on deactivate."""
    cs2_window._game_mode_dscp_policy = "NetBoost_cs2_x"
    cs2_window._game_mode_applied = False

    with patch("core.bandwidth_manager.remove_dscp_policy") as remove_dscp:
        MainWindow._deactivate_game_mode(cs2_window)

    remove_dscp.assert_called_once_with("NetBoost_cs2_x")
    assert cs2_window._game_mode_dscp_policy is None


def test_cs2_stable_ping_toast_uses_cs2_label(cs2_window):
    """Stable-ping toast must say CS2, not VALORANT."""
    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=True), \
         patch("core.bandwidth_manager._sanitise_name", return_value="x"):
        proc_cls.return_value.exe.return_value = r"C:\cs2.exe"
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    success_toasts = [m for m in cs2_window._toast.messages if m[1] == "success"]
    assert success_toasts, "expected at least one success toast"
    assert any("CS2" in msg for msg, _level, _dur in success_toasts)
    assert not any("VALORANT" in msg for msg, _level, _dur in success_toasts)
