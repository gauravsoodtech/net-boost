"""
Tests for the CS2-specific MainWindow Game Mode wiring.

CS2 has no kernel anti-cheat, so its auto plan covers all four sections:
Wi-Fi (6-key bundle), FPS Booster (CPU + NVIDIA), Background Killer (4
services), and a per-app DSCP EF (46) QoS policy.  Valorant must never
enter the wider paths.
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


# ---------------------------------------------------------------------------
# Wi-Fi section
# ---------------------------------------------------------------------------

def test_cs2_game_mode_applies_extended_wifi_bundle(cs2_window):
    from core.stable_ping_policy import cs2_wifi_settings

    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=True), \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_x"):
        proc_cls.return_value.exe.return_value = r"C:\Steam\cs2\bin\cs2.exe"
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    cs2_window._apply_wifi.assert_called_once_with(cs2_wifi_settings())


# ---------------------------------------------------------------------------
# FPS section — primary cause of stutters
# ---------------------------------------------------------------------------

def test_cs2_game_mode_applies_fps_bundle(cs2_window):
    from core.stable_ping_policy import cs2_fps_settings

    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=True), \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_x"):
        proc_cls.return_value.exe.return_value = r"C:\cs2.exe"
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    cs2_window._apply_fps.assert_called_once_with(cs2_fps_settings())


def test_cs2_game_mode_starts_gpu_temp_timer_because_nvidia_keys_are_on(cs2_window):
    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=True), \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_x"):
        proc_cls.return_value.exe.return_value = r"C:\cs2.exe"
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    assert cs2_window._gpu_temp_timer.started is True


def test_cs2_fps_bundle_excludes_disable_hags_and_visual_effects(cs2_window):
    """Reboot-required / desktop-invasive keys must stay manual."""
    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=True), \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_x"):
        proc_cls.return_value.exe.return_value = r"C:\cs2.exe"
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    fps_call_args = cs2_window._apply_fps.call_args[0][0]
    assert fps_call_args["disable_hags"] is False
    assert fps_call_args["visual_effects_off"] is False


# ---------------------------------------------------------------------------
# Optimizer section — background bandwidth contention
# ---------------------------------------------------------------------------

def test_cs2_game_mode_applies_background_killer_bundle(cs2_window):
    from core.stable_ping_policy import cs2_optimizer_settings

    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=True), \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_x"):
        proc_cls.return_value.exe.return_value = r"C:\cs2.exe"
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    cs2_window._apply_optimizer.assert_called_once_with(cs2_optimizer_settings())


def test_cs2_optimizer_bundle_does_not_carry_tcp_keys(cs2_window):
    """CS2 is UDP — TCP tweaks must not be in the auto plan."""
    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=True), \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_x"):
        proc_cls.return_value.exe.return_value = r"C:\cs2.exe"
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    opt_call_args = cs2_window._apply_optimizer.call_args[0][0]
    assert opt_call_args["tcp_no_delay"] is False
    assert opt_call_args["tcp_ack_freq"] is False
    assert opt_call_args["tcp_window_scale"] is False
    assert opt_call_args["switch_dns"] is False
    assert opt_call_args["pause_telemetry"] is True


# ---------------------------------------------------------------------------
# Monitor tab integration
# ---------------------------------------------------------------------------

def test_cs2_game_mode_populates_monitor_with_all_four_sections(cs2_window):
    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=True), \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_x"):
        proc_cls.return_value.exe.return_value = r"C:\cs2.exe"
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    # DSCP is tracked separately via _game_mode_dscp_policy, not in
    # _applied_settings (which is per-tab).  The three tab sections should
    # all be present.
    assert set(cs2_window._applied_settings) == {"wifi", "fps", "optimizer"}
    assert cs2_window._game_mode_dscp_policy == "NetBoost_cs2_x"


# ---------------------------------------------------------------------------
# DSCP section (unchanged behaviour — kept from prior session)
# ---------------------------------------------------------------------------

def test_cs2_game_mode_creates_dscp_policy(cs2_window):
    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=True) as apply_dscp, \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_deadbeef"):
        proc_cls.return_value.exe.return_value = r"C:\Steam\cs2\bin\cs2.exe"
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

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
    # Wi-Fi / FPS / Optimizer all still applied so game mode stays active.
    assert cs2_window._game_mode_applied is True
    cs2_window._apply_fps.assert_called_once()
    cs2_window._apply_optimizer.assert_called_once()


def test_cs2_game_mode_skips_dscp_when_exe_path_unavailable(cs2_window):
    import psutil

    with patch("psutil.Process", side_effect=psutil.NoSuchProcess(4242)), \
         patch("core.bandwidth_manager.apply_dscp_policy") as apply_dscp:
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    apply_dscp.assert_not_called()
    assert cs2_window._game_mode_dscp_policy is None


def test_cs2_dscp_apply_failure_does_not_break_other_sections(cs2_window):
    with patch("psutil.Process") as proc_cls, \
         patch("core.bandwidth_manager.apply_dscp_policy", return_value=False), \
         patch("core.bandwidth_manager._sanitise_name", return_value="cs2_x"):
        proc_cls.return_value.exe.return_value = r"C:\cs2.exe"
        MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    # Wi-Fi / FPS / Optimizer still applied; DSCP did not stick.
    assert cs2_window._game_mode_dscp_policy is None
    assert cs2_window._game_mode_applied is True
    cs2_window._apply_wifi.assert_called_once()
    cs2_window._apply_fps.assert_called_once()
    cs2_window._apply_optimizer.assert_called_once()
    # state_guard records BEFORE the apply attempt for crash-safety.
    cs2_window.state_guard.add_qos_policy.assert_called_once()


def test_valorant_game_mode_never_enters_cs2_paths(cs2_window):
    """Valorant must not regress into DSCP / FPS / Optimizer auto-apply."""
    with patch("core.bandwidth_manager.apply_dscp_policy") as apply_dscp:
        MainWindow._activate_game_mode(cs2_window, "VALORANT-Win64-Shipping.exe")

    apply_dscp.assert_not_called()
    cs2_window.state_guard.add_qos_policy.assert_not_called()
    assert cs2_window._game_mode_dscp_policy is None
    cs2_window._apply_fps.assert_not_called()
    cs2_window._apply_optimizer.assert_not_called()


def test_deactivate_game_mode_removes_dscp_policy(cs2_window):
    cs2_window._game_mode_dscp_policy = "NetBoost_cs2_foo"
    cs2_window._game_mode_applied = True

    with patch("core.bandwidth_manager.remove_dscp_policy") as remove_dscp:
        MainWindow._deactivate_game_mode(cs2_window)

    remove_dscp.assert_called_once_with("NetBoost_cs2_foo")
    assert cs2_window._game_mode_dscp_policy is None


def test_deactivate_removes_dscp_even_when_other_sections_failed(cs2_window):
    """Edge case: DSCP succeeded but the other applies failed.
    _game_mode_applied is False, but the QoS policy must still come down."""
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
