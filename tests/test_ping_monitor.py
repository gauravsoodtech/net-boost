"""
Tests for PingMonitor: jitter + packet loss math, timeout handling, deque rolling window.
Does NOT require a real network — uses synthetic readings via monkey-patching.
"""
import os
import sys
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock
from PyQt5.QtCore import Qt


# We need a QApplication for QThread
@pytest.fixture(scope="module")
def qt_app():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class TestPingMonitorMath:
    """Unit tests for jitter and loss calculation logic — no threads needed."""

    def _make_monitor(self, host="1.1.1.1", interval_ms=500, history_size=120):
        """Create a PingMonitor without starting the thread."""
        from core.ping_monitor import PingMonitor
        m = PingMonitor(host=host, interval_ms=interval_ms, history_size=history_size)
        return m

    def test_initial_state(self, qt_app):
        m = self._make_monitor()
        assert m.get_jitter() == 0.0
        assert m.get_loss_pct() == 0.0
        assert m.get_history() == []

    def test_jitter_single_reading(self, qt_app):
        """Single reading → jitter = 0."""
        m = self._make_monitor()
        m._history.append((20.0, False))
        assert m.get_jitter() == 0.0

    def test_jitter_uniform_readings(self, qt_app):
        """Uniform latency → jitter = 0."""
        m = self._make_monitor()
        for _ in range(10):
            m._history.append((30.0, False))
        assert m.get_jitter() == pytest.approx(0.0, abs=1e-9)

    def test_jitter_varying_readings(self, qt_app):
        """Known readings → predictable jitter."""
        m = self._make_monitor()
        readings = [10.0, 20.0, 10.0, 20.0]  # alternates by 10ms
        for r in readings:
            m._history.append((r, False))
        # jitter = std dev of successful readings
        jitter = m.get_jitter()
        assert jitter > 0.0

    def test_packet_loss_zero(self, qt_app):
        """No timeouts → 0% loss."""
        m = self._make_monitor()
        for _ in range(10):
            m._history.append((30.0, False))
        assert m.get_loss_pct() == pytest.approx(0.0)

    def test_packet_loss_fifty_pct(self, qt_app):
        """5 timeouts out of 10 → 50% loss."""
        m = self._make_monitor()
        for _ in range(5):
            m._history.append((30.0, False))
        for _ in range(5):
            m._history.append((-1.0, True))
        assert m.get_loss_pct() == pytest.approx(50.0)

    def test_packet_loss_100_pct(self, qt_app):
        """All timeouts → 100% loss."""
        m = self._make_monitor()
        for _ in range(5):
            m._history.append((-1.0, True))
        assert m.get_loss_pct() == pytest.approx(100.0)

    def test_rolling_window_max_size(self, qt_app):
        """History deque should not exceed history_size."""
        m = self._make_monitor(history_size=10)
        for i in range(50):
            m._history.append(float(i))
        assert len(m._history) <= 10

    def test_history_is_rolling(self, qt_app):
        """Oldest entries dropped when deque is full."""
        m = self._make_monitor(history_size=5)
        for i in range(1, 8):
            m._history.append(float(i))
        history = m.get_history()
        assert len(history) == 5
        assert history[-1] == 7.0
        assert history[0] == 3.0  # first 2 dropped

    def test_set_host(self, qt_app):
        """set_host() updates the host attribute."""
        m = self._make_monitor()
        m.set_host("8.8.8.8")
        assert m._host == "8.8.8.8"

    def test_set_interval(self, qt_app):
        """set_interval() updates the interval."""
        m = self._make_monitor()
        m.set_interval(1000)
        assert m._interval_ms == 1000


class TestPingParsing:
    """Test the ping.exe subprocess output parsing."""

    def test_parse_ping_normal(self, qt_app):
        """Parse standard 'time=15ms' output."""
        from core.ping_monitor import PingMonitor
        m = PingMonitor()
        output = (
            "Pinging 1.1.1.1 with 32 bytes of data:\n"
            "Reply from 1.1.1.1: bytes=32 time=15ms TTL=55\n"
            "\n"
            "Ping statistics for 1.1.1.1:\n"
            "    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),\n"
        )
        latency, timed_out = m._parse_ping_output(output)
        assert timed_out is False
        assert latency == pytest.approx(15.0)

    def test_parse_ping_less_than_1ms(self, qt_app):
        """Parse 'time<1ms' output (loopback)."""
        from core.ping_monitor import PingMonitor
        m = PingMonitor()
        output = "Reply from 127.0.0.1: bytes=32 time<1ms TTL=128\n"
        latency, timed_out = m._parse_ping_output(output)
        assert timed_out is False
        assert latency < 1.0

    def test_parse_ping_timeout(self, qt_app):
        """Parse 'Request timed out' → timed_out=True."""
        from core.ping_monitor import PingMonitor
        m = PingMonitor()
        output = "Request timed out.\n"
        latency, timed_out = m._parse_ping_output(output)
        assert timed_out is True

    def test_parse_ping_host_unreachable(self, qt_app):
        """Parse 'Destination host unreachable' → timed_out=True."""
        from core.ping_monitor import PingMonitor
        m = PingMonitor()
        output = "Reply from 192.168.1.1: Destination host unreachable.\n"
        latency, timed_out = m._parse_ping_output(output)
        assert timed_out is True


class TestPingMonitorSignal:
    """Test that PingMonitor emits signals correctly (using mock _ping)."""

    def test_signal_emitted_on_reading(self, qt_app):
        """PingMonitor emits reading signal with correct values."""
        from core.ping_monitor import PingMonitor

        m = PingMonitor(host="1.1.1.1", interval_ms=100)
        received = []

        def capture(host, ms, timed_out):
            received.append((host, ms, timed_out))
            m.stop()  # stop after first reading

        # DirectConnection: signal delivered in the emitting thread,
        # bypassing the event queue (which isn't pumped while wait() blocks).
        m.reading.connect(capture, Qt.DirectConnection)

        # Mock _ping to return fixed value
        m._ping = lambda h: (42.0, False)
        m.start()
        m.wait(3000)  # wait up to 3s

        assert len(received) >= 1
        host, ms, timed_out = received[0]
        assert host == "1.1.1.1"
        assert ms == pytest.approx(42.0)
        assert timed_out is False

    def test_signal_emitted_on_timeout(self, qt_app):
        """PingMonitor emits reading signal with timed_out=True on timeout."""
        from core.ping_monitor import PingMonitor

        m = PingMonitor(host="1.1.1.1", interval_ms=100)
        received = []

        def capture(host, ms, timed_out):
            received.append((host, ms, timed_out))
            m.stop()

        m.reading.connect(capture, Qt.DirectConnection)
        m._ping = lambda h: (0.0, True)
        m.start()
        m.wait(3000)

        assert len(received) >= 1
        assert received[0][2] is True
