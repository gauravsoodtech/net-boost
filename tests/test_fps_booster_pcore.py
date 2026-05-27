"""
Tests for the P-core detection + system-mask clamp path in
``core/fps_booster.py``.

Regression target: on the user's i7-13650HX the legacy frequency-only
detector returned ``0xFFFFFFFF`` because every logical processor reports
the same ``~MHz`` value (2803). That mask was then passed unmodified to
``SetProcessAffinityMask``, which Win32 rejects because the bits
``0x000FFFFF..0xFFFFFFFF`` lie outside the 20-thread system mask. CS2
auto-Game-Mode silently lost P-core pinning. These tests pin both the
parser path and the system-mask clamp.
"""
import ctypes
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Synthesizer for SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX records
# ---------------------------------------------------------------------------

_PTR_SIZE = ctypes.sizeof(ctypes.c_size_t)


def _make_proc_core_record(efficiency: int, mask: int, group: int = 0) -> bytes:
    """Synthesize one SYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX(Processor) entry."""
    size = 4 + 4 + 1 + 1 + 20 + 2 + _PTR_SIZE + 8
    rec = bytearray(size)
    # Relationship (DWORD) @ +0 = 0 (RelationProcessorCore) — already zero
    rec[4:8] = size.to_bytes(4, "little")               # Size
    # Flags @ +8 = 0
    rec[9] = efficiency & 0xFF                          # EfficiencyClass
    # Reserved[20] @ +10..+29 = 0
    rec[30:32] = (1).to_bytes(2, "little")              # GroupCount = 1
    rec[32:32 + _PTR_SIZE] = mask.to_bytes(_PTR_SIZE, "little")
    rec[32 + _PTR_SIZE:32 + _PTR_SIZE + 2] = group.to_bytes(2, "little")
    return bytes(rec)


# ---------------------------------------------------------------------------
# _parse_logical_proc_info_ex
# ---------------------------------------------------------------------------

class TestParseLogicalProcInfoEx:

    def test_hybrid_intel_layout_returns_p_core_mask(self):
        """i7-13650HX-style layout: 6 P-cores (eff 1) × 2 SMT + 8 E-cores (eff 0)."""
        from core.fps_booster import _parse_logical_proc_info_ex

        records = b""
        # 6 P-cores, each owning 2 logical processors (HT). Threads 0-11.
        for core_idx in range(6):
            mask = (0b11 << (core_idx * 2))
            records += _make_proc_core_record(efficiency=1, mask=mask)
        # 8 E-cores, each owning 1 logical processor. Threads 12-19.
        for core_idx in range(8):
            mask = (1 << (12 + core_idx))
            records += _make_proc_core_record(efficiency=0, mask=mask)

        p_mask = _parse_logical_proc_info_ex(records, len(records))
        assert p_mask == 0x0FFF, f"expected 0x0FFF, got 0x{p_mask:X}"

    def test_non_hybrid_returns_none(self):
        """All cores at the same EfficiencyClass → None (not hybrid)."""
        from core.fps_booster import _parse_logical_proc_info_ex

        records = b"".join(
            _make_proc_core_record(efficiency=0, mask=(1 << i))
            for i in range(8)
        )
        assert _parse_logical_proc_info_ex(records, len(records)) is None

    def test_single_core_returns_none(self):
        """Fewer than 2 cores in buffer → None."""
        from core.fps_booster import _parse_logical_proc_info_ex

        records = _make_proc_core_record(efficiency=1, mask=0x1)
        assert _parse_logical_proc_info_ex(records, len(records)) is None

    def test_empty_buffer_returns_none(self):
        from core.fps_booster import _parse_logical_proc_info_ex
        assert _parse_logical_proc_info_ex(b"", 0) is None

    def test_three_efficiency_classes_picks_highest(self):
        """Arrow Lake-style 3-tier layout (P / E / LP-E) → picks top class only."""
        from core.fps_booster import _parse_logical_proc_info_ex

        records = (
            _make_proc_core_record(efficiency=2, mask=0x1)   # P-core
            + _make_proc_core_record(efficiency=2, mask=0x2) # P-core
            + _make_proc_core_record(efficiency=1, mask=0x4) # E-core
            + _make_proc_core_record(efficiency=0, mask=0x8) # LP-E core
        )
        assert _parse_logical_proc_info_ex(records, len(records)) == 0x3

    def test_other_processor_group_ignored(self):
        """Logical processors in group != 0 are not included in the mask."""
        from core.fps_booster import _parse_logical_proc_info_ex

        records = (
            _make_proc_core_record(efficiency=1, mask=0x1, group=0)
            + _make_proc_core_record(efficiency=1, mask=0x2, group=1)  # ignored
            + _make_proc_core_record(efficiency=0, mask=0x10, group=0)
        )
        assert _parse_logical_proc_info_ex(records, len(records)) == 0x1


# ---------------------------------------------------------------------------
# _detect_p_cores_winapi
# ---------------------------------------------------------------------------

class TestDetectPCoresWinapi:

    @patch("core.fps_booster.ctypes.windll")
    def test_returns_none_when_probe_returns_zero_length(self, mock_windll):
        from core.fps_booster import _detect_p_cores_winapi

        def get_info_ex(rel, buf, length_ref):
            return 0  # leave length at 0

        mock_windll.kernel32.GetLogicalProcessorInformationEx.side_effect = get_info_ex
        assert _detect_p_cores_winapi() is None

    @patch("core.fps_booster._parse_logical_proc_info_ex", return_value=0x0FFF)
    @patch("core.fps_booster.ctypes.windll")
    def test_returns_parsed_mask_when_buffer_filled(self, mock_windll, mock_parse):
        from core.fps_booster import _detect_p_cores_winapi

        call_state = {"count": 0}

        def get_info_ex(rel, buf, length_ref):
            call_state["count"] += 1
            if call_state["count"] == 1:
                # Probe: set length via the byref'd DWORD.
                length_ref._obj.value = 96
                return 0
            return 1  # second call succeeds

        mock_windll.kernel32.GetLogicalProcessorInformationEx.side_effect = get_info_ex
        assert _detect_p_cores_winapi() == 0x0FFF

    @patch("core.fps_booster.ctypes.windll")
    def test_returns_none_on_exception(self, mock_windll):
        from core.fps_booster import _detect_p_cores_winapi
        mock_windll.kernel32.GetLogicalProcessorInformationEx.side_effect = RuntimeError("boom")
        assert _detect_p_cores_winapi() is None


# ---------------------------------------------------------------------------
# detect_hybrid_cpu_p_core_mask — layering
# ---------------------------------------------------------------------------

class TestDetectHybridLayering:

    @patch("core.fps_booster._detect_p_cores_winapi", return_value=0x0FFF)
    def test_winapi_wins_when_it_succeeds(self, mock_winapi):
        """Win32 mask is returned without consulting the frequency fallback."""
        from core.fps_booster import detect_hybrid_cpu_p_core_mask
        assert detect_hybrid_cpu_p_core_mask() == 0x0FFF

    @patch("core.fps_booster._read_hklm")
    @patch("core.fps_booster._detect_p_cores_winapi", return_value=None)
    def test_falls_through_to_frequency_when_winapi_returns_none(
        self, mock_winapi, mock_read
    ):
        """User's regression: uniform ~MHz → frequency fallback returns 0xFFFFFFFF.

        On the i7-13650HX every logical CPU registers 2803 MHz in
        HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\<N>\\~MHz, so the
        frequency comparator legitimately cannot distinguish P from E and
        must surrender the sentinel value. The set_p_core_affinity clamp
        is then responsible for keeping Win32 happy.
        """
        # 20 logical processors all at 2803 MHz (i7-13650HX live registry).
        def side_effect(subkey, value_name):
            idx = subkey.split("\\")[-1]
            if idx.isdigit() and int(idx) < 20:
                return 2803
            return None
        mock_read.side_effect = side_effect

        from core.fps_booster import detect_hybrid_cpu_p_core_mask
        assert detect_hybrid_cpu_p_core_mask() == 0xFFFFFFFF


# ---------------------------------------------------------------------------
# set_p_core_affinity — system-mask clamp
# ---------------------------------------------------------------------------

class TestSetPCoreAffinityClamp:
    """The actual production bug: a 0xFFFFFFFF mask must be clamped to the
    live system affinity (e.g. 0xFFFFF on a 20-thread CPU) before being
    passed to SetProcessAffinityMask, or Win32 returns FALSE and the FPS
    apply path loses P-core pinning."""

    def _make_kernel32(self, system_mask: int, current_mask: int,
                       set_returns: int = 1):
        """Build a MagicMock that mimics OpenProcess + GetProcessAffinityMask + Set."""
        kernel32 = MagicMock()
        kernel32.OpenProcess.return_value = 0xDEADBEEF  # non-zero handle

        def _get_affinity(handle, current_ref, system_ref):
            current_ref._obj.value = current_mask
            system_ref._obj.value = system_mask
            return 1
        kernel32.GetProcessAffinityMask.side_effect = _get_affinity

        kernel32.SetProcessAffinityMask.return_value = set_returns
        return kernel32

    @patch("core.fps_booster.detect_hybrid_cpu_p_core_mask", return_value=0xFFFFFFFF)
    @patch("core.fps_booster.ctypes.windll")
    def test_clamps_sentinel_to_current_when_already_full(self, mock_windll, mock_detect):
        """Sentinel mask (no detection) on a 20-thread CPU with PID already
        running on all 20 threads → no SetProcessAffinityMask call (no-op).

        This is the exact path that fired on the user's CS2 launch."""
        kernel32 = self._make_kernel32(system_mask=0xFFFFF, current_mask=0xFFFFF)
        mock_windll.kernel32 = kernel32

        from core.fps_booster import set_p_core_affinity
        old = set_p_core_affinity(1234)
        assert old == 0xFFFFF
        kernel32.SetProcessAffinityMask.assert_not_called()
        kernel32.CloseHandle.assert_called_once_with(0xDEADBEEF)

    @patch("core.fps_booster.detect_hybrid_cpu_p_core_mask", return_value=0x0FFF)
    @patch("core.fps_booster.ctypes.windll")
    def test_passes_clamped_mask_to_setaffinity(self, mock_windll, mock_detect):
        """When detection returns 0x0FFF and system mask is 0xFFFFF, the
        clamped value (0x0FFF & 0xFFFFF = 0x0FFF) is what Win32 receives."""
        kernel32 = self._make_kernel32(system_mask=0xFFFFF, current_mask=0xFFFFF)
        mock_windll.kernel32 = kernel32

        from core.fps_booster import set_p_core_affinity
        old = set_p_core_affinity(1234)
        assert old == 0xFFFFF
        kernel32.SetProcessAffinityMask.assert_called_once()
        # Second positional arg is the c_size_t mask.
        args = kernel32.SetProcessAffinityMask.call_args[0]
        assert args[0] == 0xDEADBEEF  # handle
        passed_mask = args[1].value if hasattr(args[1], "value") else args[1]
        assert passed_mask == 0x0FFF

    @patch("core.fps_booster.detect_hybrid_cpu_p_core_mask", return_value=0xFFFFFFFF)
    @patch("core.fps_booster.ctypes.windll")
    def test_no_setaffinity_call_when_detection_disjoint_from_system(
        self, mock_windll, mock_detect
    ):
        """If detected mask & system_mask == 0 (no overlap), don't call
        SetProcessAffinityMask with 0 — Win32 rejects that too. Leave
        affinity untouched and return the old mask."""
        # Pretend detection returned a wildly invalid mask and the system
        # mask happens to be disjoint (synthetic; real CPUs never hit this,
        # but we still don't want a crash).
        mock_detect.return_value = 0xF00000000  # bits >32 only
        kernel32 = self._make_kernel32(system_mask=0xFFFFF, current_mask=0x1)
        mock_windll.kernel32 = kernel32

        from core.fps_booster import set_p_core_affinity
        old = set_p_core_affinity(1234)
        assert old == 0x1
        kernel32.SetProcessAffinityMask.assert_not_called()

    @patch("core.fps_booster.detect_hybrid_cpu_p_core_mask", return_value=0x0FFF)
    @patch("core.fps_booster.ctypes.windll")
    def test_raises_when_setaffinity_returns_false(self, mock_windll, mock_detect):
        """Genuine Win32 failures still surface as OSError."""
        kernel32 = self._make_kernel32(
            system_mask=0xFFFFF, current_mask=0xFFFFF, set_returns=0
        )
        mock_windll.kernel32 = kernel32

        from core.fps_booster import set_p_core_affinity
        with pytest.raises(OSError, match="SetProcessAffinityMask failed"):
            set_p_core_affinity(1234)
        kernel32.CloseHandle.assert_called_once_with(0xDEADBEEF)

    @patch("core.fps_booster.detect_hybrid_cpu_p_core_mask", return_value=0x0FFF)
    @patch("core.fps_booster.ctypes.windll")
    def test_openprocess_failure_raises(self, mock_windll, mock_detect):
        kernel32 = MagicMock()
        kernel32.OpenProcess.return_value = 0
        mock_windll.kernel32 = kernel32

        from core.fps_booster import set_p_core_affinity
        with pytest.raises(OSError, match="OpenProcess failed"):
            set_p_core_affinity(1234)
