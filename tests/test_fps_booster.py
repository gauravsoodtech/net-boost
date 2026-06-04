"""
Tests for core/fps_booster.py — hybrid CPU detection, animation helpers.
"""
import ctypes
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock, call


class TestDetectHybridCpuPCoreMask:
    """Tests for the frequency-based fallback path.

    The primary detection path is ``_detect_p_cores_winapi``; these tests
    force it to ``None`` so each case exercises the frequency comparator
    in isolation.
    """

    @patch("core.fps_booster._detect_p_cores_winapi", return_value=None)
    @patch("core.fps_booster._read_hklm")
    def test_uniform_frequency_returns_all_cores(self, mock_read, mock_winapi):
        """All cores at same frequency → not hybrid → 0xFFFFFFFF."""
        # 8 cores all at 2400 MHz
        def side_effect(subkey, value_name):
            idx = subkey.split("\\")[-1]
            if idx.isdigit() and int(idx) < 8:
                return 2400
            return None
        mock_read.side_effect = side_effect

        from core.fps_booster import detect_hybrid_cpu_p_core_mask
        assert detect_hybrid_cpu_p_core_mask() == 0xFFFFFFFF

    @patch("core.fps_booster._detect_p_cores_winapi", return_value=None)
    @patch("core.fps_booster._read_hklm")
    def test_mixed_frequencies_returns_p_core_mask(self, mock_read, mock_winapi):
        """P-cores at 2400, E-cores at 1800 → only P-core bits set."""
        # 4 P-cores (2400) + 4 E-cores (1800)
        freqs = [2400, 2400, 2400, 2400, 1800, 1800, 1800, 1800]

        def side_effect(subkey, value_name):
            idx = subkey.split("\\")[-1]
            if idx.isdigit() and int(idx) < len(freqs):
                return freqs[int(idx)]
            return None
        mock_read.side_effect = side_effect

        from core.fps_booster import detect_hybrid_cpu_p_core_mask
        mask = detect_hybrid_cpu_p_core_mask()
        # P-cores are indices 0-3 → mask = 0b00001111 = 0x0F
        assert mask == 0x0F

    @patch("core.fps_booster._detect_p_cores_winapi", return_value=None)
    @patch("core.fps_booster._read_hklm")
    def test_registry_failure_returns_all_cores(self, mock_read, mock_winapi):
        """Registry read raises → fallback 0xFFFFFFFF."""
        mock_read.side_effect = OSError("access denied")

        from core.fps_booster import detect_hybrid_cpu_p_core_mask
        assert detect_hybrid_cpu_p_core_mask() == 0xFFFFFFFF

    @patch("core.fps_booster._detect_p_cores_winapi", return_value=None)
    @patch("core.fps_booster._read_hklm")
    def test_single_core_returns_all_cores(self, mock_read, mock_winapi):
        """Fewer than 2 cores detected → fallback."""
        def side_effect(subkey, value_name):
            idx = subkey.split("\\")[-1]
            if idx == "0":
                return 3600
            return None
        mock_read.side_effect = side_effect

        from core.fps_booster import detect_hybrid_cpu_p_core_mask
        assert detect_hybrid_cpu_p_core_mask() == 0xFFFFFFFF


class TestGetAnimationState:

    @patch("ctypes.windll")
    def test_get_animation_state_calls_system_parameters(self, mock_windll):
        """_get_animation_state reads SPI_GETANIMATION via SystemParametersInfoW."""
        mock_windll.user32.SystemParametersInfoW.return_value = 1

        from core.fps_booster import _get_animation_state, _SPI_GETANIMATION
        # The function creates an ANIMATIONINFO struct and calls SystemParametersInfoW.
        # We just verify no crash and it returns an int.
        result = _get_animation_state()
        assert isinstance(result, int)
        mock_windll.user32.SystemParametersInfoW.assert_called_once()
        # First arg should be SPI_GETANIMATION
        args = mock_windll.user32.SystemParametersInfoW.call_args[0]
        assert args[0] == _SPI_GETANIMATION


class TestDisableAnimations:

    @patch("core.fps_booster._get_animation_state", return_value=1)
    @patch("ctypes.windll")
    def test_disable_returns_previous_state(self, mock_windll, mock_get):
        """_disable_animations returns the previous iMinAnimate value."""
        from core.fps_booster import _disable_animations
        prev = _disable_animations()
        assert prev == 1

    @patch("core.fps_booster._get_animation_state", return_value=0)
    @patch("ctypes.windll")
    def test_disable_when_already_off(self, mock_windll, mock_get):
        """Returns 0 when animations were already disabled."""
        from core.fps_booster import _disable_animations
        prev = _disable_animations()
        assert prev == 0


class TestRestoreAnimations:

    @patch("ctypes.windll")
    def test_restore_writes_saved_value(self, mock_windll):
        """_restore_animations writes the provided value, not a hardcoded 1."""
        from core.fps_booster import _restore_animations, _SPI_SETANIMATION
        _restore_animations(0)
        mock_windll.user32.SystemParametersInfoW.assert_called_once()
        args = mock_windll.user32.SystemParametersInfoW.call_args[0]
        assert args[0] == _SPI_SETANIMATION

    @patch("ctypes.windll")
    def test_restore_with_value_1(self, mock_windll):
        """_restore_animations(1) does not crash."""
        from core.fps_booster import _restore_animations
        _restore_animations(1)
        mock_windll.user32.SystemParametersInfoW.assert_called_once()


class TestApplyVerification:
    """apply() records read-back / behavioural verification in backup['_verify'].

    Affinity and timer resolution are deliberately excluded — affinity is
    transient (the game re-pins itself) and timer resolution is a shared global
    minimum, so read-back there would be misleading rather than useful.
    """

    @patch("core.fps_booster.set_power_plan")
    @patch("core.fps_booster._ensure_ultimate_perf_plan", return_value="TARGET-GUID")
    @patch("core.fps_booster.get_active_power_plan")
    def test_power_plan_verified_when_active_scheme_matches(self, mock_get, mock_ensure, mock_set):
        from core import fps_booster
        mock_get.side_effect = ["ORIG-GUID", "TARGET-GUID"]  # original, then verify read
        backup = fps_booster.apply({"power_plan": True})
        v = backup["_verify"]
        assert v["verified"] == 1 and v["failed"] == 0
        assert "power_plan" in v["verified_values"]

    @patch("core.fps_booster.set_power_plan")
    @patch("core.fps_booster._ensure_ultimate_perf_plan", return_value="TARGET-GUID")
    @patch("core.fps_booster.get_active_power_plan")
    def test_power_plan_failed_when_scheme_did_not_change(self, mock_get, mock_ensure, mock_set):
        from core import fps_booster
        mock_get.side_effect = ["ORIG-GUID", "SOMETHING-ELSE"]
        backup = fps_booster.apply({"power_plan": True})
        v = backup["_verify"]
        assert v["failed"] == 1
        assert v["failed_values"][0]["reason"] == "active scheme did not change"

    @patch("core.fps_booster._write_hkcu")
    @patch("core.fps_booster._read_hkcu")
    def test_game_dvr_verified_on_readback_zero(self, mock_read, mock_write):
        import winreg
        from core import fps_booster
        mock_read.side_effect = [(1, winreg.REG_DWORD), (0, winreg.REG_DWORD)]  # prev, then verify
        backup = fps_booster.apply({"game_dvr_off": True})
        assert backup["_verify"]["verified"] == 1
        assert backup["_verify"]["failed"] == 0

    @patch("core.fps_booster._write_hkcu")
    @patch("core.fps_booster._read_hkcu")
    def test_game_dvr_failed_when_readback_nonzero(self, mock_read, mock_write):
        import winreg
        from core import fps_booster
        mock_read.side_effect = [None, (1, winreg.REG_DWORD)]  # absent before, still 1 after
        backup = fps_booster.apply({"game_dvr_off": True})
        assert backup["_verify"]["failed"] == 1
        assert backup["_verify"]["failed_values"][0]["reason"] == "readback mismatch"

    @patch("core.fps_booster._sysmain_is_stopped", return_value=True)
    @patch("core.fps_booster._stop_sysmain", return_value=True)
    def test_sysmain_verified_when_service_stopped(self, mock_stop, mock_status):
        from core import fps_booster
        backup = fps_booster.apply({"sysmain_off": True})
        assert backup["_verify"]["verified"] == 1

    @patch("core.fps_booster._sysmain_is_stopped", return_value=None)
    @patch("core.fps_booster._stop_sysmain", return_value=True)
    def test_sysmain_unreadable_status_records_nothing(self, mock_stop, mock_status):
        from core import fps_booster
        backup = fps_booster.apply({"sysmain_off": True})
        v = backup["_verify"]
        assert v["written"] == 0 and v["verified"] == 0 and v["failed"] == 0

    @patch("core.fps_booster._get_animation_state", return_value=0)
    @patch("core.fps_booster._disable_animations", return_value=1)
    def test_visual_effects_verified_when_animations_off(self, mock_disable, mock_state):
        from core import fps_booster
        backup = fps_booster.apply({"visual_effects_off": True})
        assert backup["_verify"]["verified"] == 1

    @patch("core.fps_booster._set_fullscreen_opt", return_value=None)
    @patch("core.fps_booster._get_process_path", return_value=r"C:\game.exe")
    @patch("core.fps_booster._read_hkcu")
    def test_fullscreen_opt_verified_when_flag_present(self, mock_read, mock_path, mock_set):
        import winreg
        from core import fps_booster
        mock_read.return_value = ("DISABLEDXMAXIMIZEDWINDOWEDMODE", winreg.REG_SZ)
        backup = fps_booster.apply({"fullscreen_opt_off": True}, game_pid=1234)
        assert backup["_verify"]["verified"] == 1

    @patch("core.fps_booster.set_timer_resolution")
    @patch("core.fps_booster.set_p_core_affinity", return_value=0xFF)
    def test_affinity_and_timer_are_deliberately_not_verified(self, mock_aff, mock_timer):
        from core import fps_booster
        backup = fps_booster.apply(
            {"pcores_affinity": True, "timer_resolution": True}, game_pid=1234
        )
        v = backup["_verify"]
        assert v["written"] == 0 and v["verified"] == 0 and v["failed"] == 0
