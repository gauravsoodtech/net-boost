"""
ping_monitor.py — QThread-based ICMP ping monitor for NetBoost.

Emits per-reading signals that the UI can consume to update the live latency
graph and statistics widgets.  Uses a raw ICMP socket when running with
administrator privileges, and falls back to parsing Windows ``ping.exe``
output otherwise.
"""

import logging
import os
import re
import socket
import struct
import subprocess
import time
from collections import deque
from statistics import stdev
from typing import Tuple

from PyQt5.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ICMP helpers
# ---------------------------------------------------------------------------

_ICMP_ECHO_REQUEST = 8   # ICMP type for echo request
_ICMP_CODE = 0
_ICMP_HEADER_FORMAT = "bbHHh"   # type, code, checksum, id, seq


def _checksum(data: bytes) -> int:
    """Calculate the standard Internet checksum over *data*."""
    if len(data) % 2 != 0:
        data += b"\x00"
    total = 0
    for i in range(0, len(data), 2):
        word = (data[i] << 8) + data[i + 1]
        total += word
    # Fold 32-bit sum into 16 bits.
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def _build_icmp_packet(identifier: int, sequence: int) -> bytes:
    """Build a 28-byte ICMP echo-request packet."""
    # Pack header with zero checksum first.
    header = struct.pack(_ICMP_HEADER_FORMAT, _ICMP_ECHO_REQUEST, _ICMP_CODE, 0, identifier, sequence)
    # 20 bytes of payload filled with sequential bytes.
    payload = bytes(range(20))
    chk = _checksum(header + payload)
    header = struct.pack(_ICMP_HEADER_FORMAT, _ICMP_ECHO_REQUEST, _ICMP_CODE, chk, identifier, sequence)
    return header + payload


# ---------------------------------------------------------------------------
# PingMonitor
# ---------------------------------------------------------------------------

class PingMonitor(QThread):
    """
    Background thread that pings a target host at a configurable interval.

    Signals
    -------
    reading(host: str, latency_ms: float, timed_out: bool)
        Emitted after each probe.  *latency_ms* is ``-1.0`` when *timed_out*
        is ``True``.
    """

    reading = pyqtSignal(str, float, bool)  # host, latency_ms, timed_out

    def __init__(
        self,
        host: str = "1.1.1.1",
        interval_ms: int = 500,
        history_size: int = 120,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._host = host
        self._interval_ms = interval_ms
        self._history_size = history_size
        self._running = False
        # Each entry is (latency_ms, timed_out).
        self._history: deque[Tuple[float, bool]] = deque(maxlen=history_size)
        self._sequence = 0
        self._identifier = os.getpid() & 0xFFFF
        self._raw_consecutive_timeouts = 0   # switch to subprocess when raw ICMP is blocked

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._running = True
        logger.info("PingMonitor started (host=%s, interval=%dms).", self._host, self._interval_ms)
        while self._running:
            host = self._host  # snapshot in case set_host() races
            t_start = time.perf_counter()

            latency, timed_out = self._ping(host)
            self._history.append((latency, timed_out))
            self.reading.emit(host, latency, timed_out)

            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            sleep_ms = max(0.0, self._interval_ms - elapsed_ms)
            # Sleep in small slices so stop() responds quickly.
            slept = 0.0
            slice_ms = 50.0
            while self._running and slept < sleep_ms:
                actual_slice = min(slice_ms, sleep_ms - slept)
                time.sleep(actual_slice / 1000.0)
                slept += actual_slice

        logger.info("PingMonitor stopped.")

    # ------------------------------------------------------------------
    # Ping implementation
    # ------------------------------------------------------------------

    def _ping(self, host: str) -> Tuple[float, bool]:
        """
        Probe *host* and return ``(latency_ms, timed_out)``.

        Attempts a raw ICMP socket first; falls back to ``ping.exe`` if the
        raw socket cannot be created (typically when not running as admin).
        """
        self._sequence = (self._sequence + 1) & 0xFFFF
        seq = self._sequence
        ident = self._identifier

        # --- Raw ICMP attempt (skip if driver-level blocking detected) ---
        if self._raw_consecutive_timeouts < 5:
            try:
                result = self._ping_raw(host, ident, seq)
                if result[1]:  # timed_out — may be kernel-level interception (e.g. Vanguard)
                    self._raw_consecutive_timeouts += 1
                    if self._raw_consecutive_timeouts >= 5:
                        logger.debug(
                            "Raw ICMP timed out 5× in a row — switching to ping.exe fallback "
                            "(likely blocked by kernel anti-cheat)."
                        )
                else:
                    self._raw_consecutive_timeouts = 0  # reset on success
                return result
            except PermissionError:
                logger.debug("Raw ICMP socket unavailable; using ping.exe fallback.")
                self._raw_consecutive_timeouts = 5  # skip raw permanently this session
            except OSError as exc:
                logger.debug("Raw ICMP failed (%s); using ping.exe fallback.", exc)
                self._raw_consecutive_timeouts = 5

        # --- subprocess fallback ---
        return self._ping_subprocess(host)

    def _ping_raw(self, host: str, ident: int, seq: int) -> Tuple[float, bool]:
        """Send a raw ICMP echo request and wait for the reply."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        sock.settimeout(2.0)
        try:
            packet = _build_icmp_packet(ident, seq)
            t_send = time.perf_counter()
            sock.sendto(packet, (host, 0))

            while True:
                try:
                    raw_reply, addr = sock.recvfrom(1024)
                except socket.timeout:
                    return -1.0, True

                t_recv = time.perf_counter()
                # IP header is 20 bytes; ICMP reply starts after.
                if len(raw_reply) < 28:
                    continue
                icmp_type = raw_reply[20]
                # Type 0 = Echo Reply
                if icmp_type != 0:
                    continue
                # Extract id and sequence from the reply.
                reply_id = struct.unpack("!H", raw_reply[24:26])[0]
                reply_seq = struct.unpack("!H", raw_reply[26:28])[0]
                if reply_id == ident and reply_seq == seq:
                    latency = (t_recv - t_send) * 1000.0
                    return round(latency, 2), False
        finally:
            sock.close()

    def _ping_subprocess(self, host: str) -> Tuple[float, bool]:
        """Fall back to parsing Windows ``ping.exe`` output."""
        try:
            result = subprocess.run(
                ["ping", "-n", "1", "-w", "2000", host],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("ping.exe subprocess failed: %s", exc)
            return -1.0, True

        return self._parse_ping_output(result.stdout)

    def _parse_ping_output(self, stdout: str) -> Tuple[float, bool]:
        """Parse ``ping.exe`` stdout and return ``(latency_ms, timed_out)``."""
        # "time<1ms" edge case — treat as 0.5 ms.
        if re.search(r"time<1ms", stdout, re.IGNORECASE):
            return 0.5, False

        # "time=XXms"
        match = re.search(r"time[=<](\d+(?:\.\d+)?)ms", stdout, re.IGNORECASE)
        if match:
            return float(match.group(1)), False

        # Request timed out or host unreachable.
        return -1.0, True

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Request the monitor thread to stop gracefully."""
        self._running = False
        logger.debug("PingMonitor stop requested.")

    @property
    def host(self) -> str:
        """Current target host."""
        return self._host

    def set_host(self, host: str) -> None:
        """Change the target host.  Takes effect on the next probe."""
        logger.debug("PingMonitor host changed to '%s'.", host)
        self._host = host
        self._history.clear()

    def set_interval(self, ms: int) -> None:
        """Change the probe interval in milliseconds.  Takes effect on the next sleep cycle."""
        logger.debug("PingMonitor interval changed to %d ms.", ms)
        self._interval_ms = ms

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_history(self) -> list:
        """Return the reading history as a list of ``(latency_ms, timed_out)`` tuples."""
        return list(self._history)

    def get_jitter(self) -> float:
        """
        Return the jitter (standard deviation of latency) in milliseconds.

        Only successful (non-timed-out) readings are included.  Returns
        ``0.0`` when fewer than two successful readings are available.
        """
        successful = [lat for lat, to in self._history if not to and lat >= 0]
        if len(successful) < 2:
            return 0.0
        return round(stdev(successful), 2)

    def get_loss_pct(self) -> float:
        """
        Return the packet loss percentage over the recorded history window.

        Returns ``0.0`` when no readings have been recorded yet.
        """
        if not self._history:
            return 0.0
        lost = sum(1 for _, timed_out in self._history if timed_out)
        return round((lost / len(self._history)) * 100.0, 1)
