"""
Tests for the CS2-specific MainWindow Game Mode wiring.

CS2 is Wi-Fi-only: its auto plan applies only the conservative 4-key Wi-Fi bundle.
FPS Booster, Optimizer (background killer / TCP / DNS), and the per-app DSCP
QoS policy are NOT auto-applied — they stay manual. Valorant and CS2 both use
the same conservative 4-key Wi-Fi subset.

The MainWindow still carries the DSCP teardown machinery (it is correct
defensive cleanup), so the deactivate tests below set a policy directly to
exercise it; the live plan simply never sets one anymore.
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
    window.state_guard = MagicMock()
    window._current_game_pid = 4242
    window._game_mode_dscp_policy = None
    return window


# ---------------------------------------------------------------------------
# Wi-Fi section — the only thing CS2 auto-applies
# ---------------------------------------------------------------------------

def test_cs2_game_mode_applies_lighter_wifi_bundle(cs2_window):
    from core.stable_ping_policy import cs2_wifi_settings

    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    cs2_window._apply_wifi.assert_called_once_with(cs2_wifi_settings())


def test_cs2_game_mode_syncs_wifi_toggles_to_badges(cs2_window):
    """The reported bug: Game Mode lit the 'Active' badge but never moved the
    toggle switch.  After activate, the switches must match the applied policy
    (so badge ⟺ toggle)."""
    from core.stable_ping_policy import cs2_wifi_settings

    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    assert cs2_window.tab_wifi.get_settings() == cs2_wifi_settings()
    assert cs2_window.tab_wifi.marked == cs2_wifi_settings()


def test_cs2_deactivate_restores_pre_game_toggles_and_clears_badges(cs2_window):
    pre_game = cs2_window.tab_wifi.get_settings()
    cs2_window._game_mode_active = True

    MainWindow._activate_game_mode(cs2_window, "cs2.exe")
    # Toggles were overwritten by the policy and badges shown.
    assert cs2_window.tab_wifi.get_settings() != pre_game
    assert cs2_window.tab_wifi.marked is not None

    MainWindow._deactivate_game_mode(cs2_window)

    # Switches back to the user's pre-game selection, badges gone.
    assert cs2_window.tab_wifi.get_settings() == pre_game
    assert cs2_window.tab_wifi.marked is None
    assert cs2_window._applied_settings == {}
    assert cs2_window._pre_game_mode_settings is None


# ---------------------------------------------------------------------------
# FPS / Optimizer / DSCP must NOT be auto-applied for CS2
# ---------------------------------------------------------------------------

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
    # Wi-Fi still applied, so game mode is active.
    assert cs2_window._game_mode_applied is True


def test_cs2_game_mode_does_not_start_gpu_temp_timer(cs2_window):
    """No NVIDIA keys are applied (no FPS bundle at all), so the nvidia-smi
    GPU-temp poller must stay stopped."""
    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    assert cs2_window._gpu_temp_timer.started is False


# ---------------------------------------------------------------------------
# Monitor tab integration — only the Wi-Fi section is populated
# ---------------------------------------------------------------------------

def test_cs2_game_mode_populates_monitor_with_wifi_only(cs2_window):
    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    assert set(cs2_window._applied_settings) == {"wifi"}
    assert cs2_window._game_mode_dscp_policy is None


# ---------------------------------------------------------------------------
# Valorant must stay narrow
# ---------------------------------------------------------------------------

def test_valorant_game_mode_stays_wifi_only(cs2_window):
    with patch("core.bandwidth_manager.apply_dscp_policy") as apply_dscp:
        MainWindow._activate_game_mode(cs2_window, "VALORANT-Win64-Shipping.exe")

    apply_dscp.assert_not_called()
    cs2_window.state_guard.add_qos_policy.assert_not_called()
    assert cs2_window._game_mode_dscp_policy is None
    cs2_window._apply_fps.assert_not_called()
    cs2_window._apply_optimizer.assert_not_called()


# ---------------------------------------------------------------------------
# DSCP teardown machinery (still present as defensive cleanup)
# ---------------------------------------------------------------------------

def test_deactivate_game_mode_removes_dscp_policy(cs2_window):
    cs2_window._game_mode_dscp_policy = "NetBoost_cs2_foo"
    cs2_window._game_mode_applied = True

    with patch("core.bandwidth_manager.remove_dscp_policy") as remove_dscp:
        MainWindow._deactivate_game_mode(cs2_window)

    remove_dscp.assert_called_once_with("NetBoost_cs2_foo")
    assert cs2_window._game_mode_dscp_policy is None


def test_deactivate_removes_dscp_even_when_other_sections_failed(cs2_window):
    """Edge case: a DSCP policy exists but the apply flow never flagged
    _game_mode_applied.  The QoS policy must still come down."""
    cs2_window._game_mode_dscp_policy = "NetBoost_cs2_x"
    cs2_window._game_mode_applied = False

    with patch("core.bandwidth_manager.remove_dscp_policy") as remove_dscp:
        MainWindow._deactivate_game_mode(cs2_window)

    remove_dscp.assert_called_once_with("NetBoost_cs2_x")
    assert cs2_window._game_mode_dscp_policy is None


# ---------------------------------------------------------------------------
# Toast labelling
# ---------------------------------------------------------------------------

def test_cs2_stable_ping_toast_uses_cs2_label(cs2_window):
    """Stable-ping toast must say CS2, not VALORANT."""
    MainWindow._activate_game_mode(cs2_window, "cs2.exe")

    success_toasts = [m for m in cs2_window._toast.messages if m[1] == "success"]
    assert success_toasts, "expected at least one success toast"
    assert any("CS2" in msg for msg, _level, _dur in success_toasts)
    assert not any("VALORANT" in msg for msg, _level, _dur in success_toasts)
