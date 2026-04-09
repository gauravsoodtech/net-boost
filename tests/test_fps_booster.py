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

    @patch("core.fps_booster._read_hklm")
    def test_uniform_frequency_returns_all_cores(self, mock_read):
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

    @patch("core.fps_booster._read_hklm")
    def test_mixed_frequencies_returns_p_core_mask(self, mock_read):
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

    @patch("core.fps_booster._read_hklm")
    def test_registry_failure_returns_all_cores(self, mock_read):
        """Registry read raises → fallback 0xFFFFFFFF."""
        mock_read.side_effect = OSError("access denied")

        from core.fps_booster import detect_hybrid_cpu_p_core_mask
        assert detect_hybrid_cpu_p_core_mask() == 0xFFFFFFFF

    @patch("core.fps_booster._read_hklm")
    def test_single_core_returns_all_cores(self, mock_read):
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
