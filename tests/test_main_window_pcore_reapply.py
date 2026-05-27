"""
Tests for the post-launch P-core re-apply window in ``MainWindow``.

Regression context: ``set_p_core_affinity`` succeeds at the moment NetBoost
fires ``_apply_fps``, but Source 2 (CS2) and many UE titles call
``SetProcessAffinityMask`` back to *all* logical processors a few seconds
into their own init, silently undoing the initial pin. The fix re-pins
the game four more times at 5 s intervals so the kernel mask outlasts
the engine's startup.
"""

from unittest.mock import MagicMock, patch

import pytest

from ui.main_window import MainWindow


# ---------------------------------------------------------------------------
# Fixture: bare MainWindow with the bits the re-apply path touches
# ---------------------------------------------------------------------------

def _make_window():
    window = MainWindow.__new__(MainWindow)
    window._pcore_reapply_timer = MagicMock()
    window._pcore_reapply_remaining = 0
    window._pcore_reapply_pid = 0
    window._current_game = None
    window._current_game_pid = 0
    return window


@pytest.fixture
def window():
    return _make_window()


# ---------------------------------------------------------------------------
# _start_pcore_reapply_window — direct
# ---------------------------------------------------------------------------

def test_start_arms_four_ticks_and_starts_timer(window):
    MainWindow._start_pcore_reapply_window(window, 4242)

    assert window._pcore_reapply_pid == 4242
    assert window._pcore_reapply_remaining == 4
    window._pcore_reapply_timer.start.assert_called_once()


def test_start_stops_in_flight_timer_before_restarting(window):
    """A second Apply must reset the countdown, not stack ticks."""
    MainWindow._start_pcore_reapply_window(window, 100)
    MainWindow._start_pcore_reapply_window(window, 200)

    # stop() called twice — once defensively per start.
    assert window._pcore_reapply_timer.stop.call_count == 2
    assert window._pcore_reapply_timer.start.call_count == 2
    # State reflects the most recent invocation.
    assert window._pcore_reapply_pid == 200
    assert window._pcore_reapply_remaining == 4


# ---------------------------------------------------------------------------
# _on_pcore_reapply_tick — direct
# ---------------------------------------------------------------------------

def test_tick_calls_set_p_core_affinity_with_stored_pid(window):
    window._pcore_reapply_pid = 4242
    window._pcore_reapply_remaining = 3

    with patch("psutil.pid_exists", return_value=True), \
         patch("core.fps_booster.set_p_core_affinity") as set_aff:
        MainWindow._on_pcore_reapply_tick(window)

    set_aff.assert_called_once_with(4242)
    assert window._pcore_reapply_remaining == 2
    window._pcore_reapply_timer.stop.assert_not_called()


def test_tick_stops_timer_on_final_iteration(window):
    window._pcore_reapply_pid = 4242
    window._pcore_reapply_remaining = 1

    with patch("psutil.pid_exists", return_value=True), \
         patch("core.fps_booster.set_p_core_affinity"):
        MainWindow._on_pcore_reapply_tick(window)

    window._pcore_reapply_timer.stop.assert_called_once()
    assert window._pcore_reapply_pid == 0
    assert window._pcore_reapply_remaining == 0


def test_tick_aborts_when_process_no_longer_exists(window):
    """Game crashed mid-window — don't keep poking a dead PID."""
    window._pcore_reapply_pid = 4242
    window._pcore_reapply_remaining = 4

    with patch("psutil.pid_exists", return_value=False), \
         patch("core.fps_booster.set_p_core_affinity") as set_aff:
        MainWindow._on_pcore_reapply_tick(window)

    set_aff.assert_not_called()
    window._pcore_reapply_timer.stop.assert_called_once()
    assert window._pcore_reapply_pid == 0
    assert window._pcore_reapply_remaining == 0


def test_tick_returns_quietly_when_pid_is_zero(window):
    """Defensive: ticking with no recorded PID does not import psutil
    or call Win32; it just stops the timer."""
    window._pcore_reapply_pid = 0
    window._pcore_reapply_remaining = 4

    with patch("core.fps_booster.set_p_core_affinity") as set_aff:
        MainWindow._on_pcore_reapply_tick(window)

    set_aff.assert_not_called()
    window._pcore_reapply_timer.stop.assert_called_once()


def test_tick_logs_and_continues_when_setaffinity_raises(window):
    """A transient Win32 failure (game momentarily not accepting handles)
    must not abort the rest of the window."""
    window._pcore_reapply_pid = 4242
    window._pcore_reapply_remaining = 3

    with patch("psutil.pid_exists", return_value=True), \
         patch("core.fps_booster.set_p_core_affinity",
               side_effect=OSError("transient")):
        MainWindow._on_pcore_reapply_tick(window)

    assert window._pcore_reapply_remaining == 2  # still decremented
    window._pcore_reapply_timer.stop.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: _apply_fps trigger
# ---------------------------------------------------------------------------

def _make_window_for_apply_fps():
    """Variant of _make_window with the FPS booster collaborator and a
    state_guard stubbed in. _apply_fps reaches for both."""
    window = _make_window()
    window._fps_booster = MagicMock()
    window._fps_booster.apply.return_value = {"power_plan": "GUID"}
    window._nvidia_optimizer = MagicMock()
    window.state_guard = MagicMock()
    window._set_status = MagicMock()
    window._current_game = "cs2.exe"
    return window


def test_apply_fps_arms_window_when_pcores_on_and_pid_found():
    window = _make_window_for_apply_fps()

    # psutil.process_iter must yield a cs2 process so _apply_fps finds a PID.
    fake_proc = MagicMock()
    fake_proc.info = {"name": "cs2.exe", "pid": 4242}

    with patch("psutil.process_iter", return_value=[fake_proc]):
        MainWindow._apply_fps(window, {"pcores_affinity": True})

    assert window._pcore_reapply_pid == 4242
    assert window._pcore_reapply_remaining == 4
    window._pcore_reapply_timer.start.assert_called_once()


def test_apply_fps_does_not_arm_window_when_pcores_off():
    window = _make_window_for_apply_fps()

    fake_proc = MagicMock()
    fake_proc.info = {"name": "cs2.exe", "pid": 4242}

    with patch("psutil.process_iter", return_value=[fake_proc]):
        MainWindow._apply_fps(window, {"pcores_affinity": False, "power_plan": True})

    window._pcore_reapply_timer.start.assert_not_called()
    assert window._pcore_reapply_pid == 0


def test_apply_fps_does_not_arm_window_when_no_game_running():
    window = _make_window_for_apply_fps()
    window._current_game = None  # nothing to pin

    with patch("psutil.process_iter", return_value=[]):
        MainWindow._apply_fps(window, {"pcores_affinity": True})

    window._pcore_reapply_timer.start.assert_not_called()
    assert window._pcore_reapply_pid == 0


# ---------------------------------------------------------------------------
# Cleanup hooks
# ---------------------------------------------------------------------------

def test_game_exited_stops_pending_reapply(window):
    # Populate state as if a window is mid-flight.
    window._pcore_reapply_pid = 4242
    window._pcore_reapply_remaining = 3
    # on_game_exited touches other UI surfaces — stub them.
    window.tab_dashboard = MagicMock()
    window.tab_route = MagicMock()
    window.tab_dashboard.set_ping_host = MagicMock()
    window.tray = None
    window.ping_monitor = None
    window._ping_host_before_game = "1.1.1.1"
    window._consecutive_jitter_spikes = 5
    window._game_mode_active = False  # avoid _deactivate_game_mode path
    window._set_status = MagicMock()

    MainWindow.on_game_exited(window, "cs2.exe")

    window._pcore_reapply_timer.stop.assert_called_once()
    assert window._pcore_reapply_pid == 0
    assert window._pcore_reapply_remaining == 0


def test_fps_restore_stops_pending_reapply(window):
    window._pcore_reapply_pid = 4242
    window._pcore_reapply_remaining = 2
    # _on_fps_restore touches more surfaces — stub them.
    window.tab_fps = MagicMock()
    window.tab_monitor = MagicMock()
    window._applied_settings = {"fps": {}}
    window._gpu_temp_timer = MagicMock()
    window._gpu_throttle_alerted = False
    window.state_guard = None
    window._fps_booster = None
    window._nvidia_optimizer = None

    MainWindow._on_fps_restore(window)

    window._pcore_reapply_timer.stop.assert_called()
    assert window._pcore_reapply_pid == 0
    assert window._pcore_reapply_remaining == 0
