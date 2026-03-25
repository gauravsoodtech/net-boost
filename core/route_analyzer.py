"""
core/route_analyzer.py
Route analyzer — discovers the game server IP from live process connections
and traces the hop-by-hop route using Windows tracert.

No Qt imports in the pure functions.  The _TraceRouteWorker and _DiscoverWorker
QRunnables live at the bottom of this module so they can be imported by the UI
without pulling Qt into core unit tests (tests mock subprocess and psutil).
"""

import ipaddress
import logging
import re
import subprocess
from typing import List, Optional

logger = logging.getLogger(__name__)


# ── Compiled regex — reused for every tracert output line ────────────────────

_HOP_PATTERN = re.compile(
    r"^\s*(?P<hop>\d+)\s+"
    r"(?P<r1>[<\d]+\s*ms|\*)\s+"
    r"(?P<r2>[<\d]+\s*ms|\*)\s+"
    r"(?P<r3>[<\d]+\s*ms|\*)\s+"
    r"(?P<rest>.+?)\s*$"
)

_MS_VALUE_PATTERN = re.compile(r"<?\s*(\d+)\s*ms")


# ── Private helpers ───────────────────────────────────────────────────────────

def _is_private_ip(ip: str) -> bool:
    """
    Return True if *ip* is loopback, link-local, or an RFC-1918 private address.

    Uses stdlib ipaddress — handles IPv4 and IPv6 without a fragile hand-rolled
    regex.  Returns True on parse failure (treat as non-routable).
    """
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return True


def _parse_ms(token: str) -> Optional[float]:
    """
    Parse one tracert RTT token into a float millisecond value.

    '<1 ms' → 0.5  (sub-millisecond stored as 0.5 so bottleneck math works)
    '5 ms'  → 5.0
    '*'     → None
    """
    token = token.strip()
    if token == "*":
        return None
    m = _MS_VALUE_PATTERN.search(token)
    if not m:
        return None
    value = int(m.group(1))
    if token.startswith("<"):
        return 0.5
    return float(value)


# ── Public parsing functions ──────────────────────────────────────────────────

def _parse_tracert_line(line: str) -> Optional[dict]:
    """
    Parse one output line from ``tracert -d`` into a hop dict, or None if the
    line is a header, blank, or informational line.

    Returned dict schema
    --------------------
    {
        "hop":          int,            # 1-based hop number
        "ip":           str or None,    # router IP; None on full timeout
        "latency_ms":   float or None,  # average of responding probes
        "min_ms":       float or None,
        "max_ms":       float or None,
        "is_timeout":   bool,           # True only if ALL three probes were *
        "is_bottleneck": bool,          # always False here; set by mark_bottlenecks()
    }
    """
    m = _HOP_PATTERN.match(line)
    if not m:
        return None

    hop  = int(m.group("hop"))
    r1   = _parse_ms(m.group("r1"))
    r2   = _parse_ms(m.group("r2"))
    r3   = _parse_ms(m.group("r3"))
    rest = m.group("rest").strip()

    readings  = [v for v in (r1, r2, r3) if v is not None]
    is_timeout = (len(readings) == 0)

    # Attempt to parse an IP from the trailing field
    ip: Optional[str] = None
    if not (is_timeout or "timed out" in rest.lower()):
        try:
            ipaddress.ip_address(rest)
            ip = rest
        except ValueError:
            pass  # rest might be a hostname or extra annotation — ignore

    latency_ms = (sum(readings) / len(readings)) if readings else None
    min_ms     = min(readings) if readings else None
    max_ms     = max(readings) if readings else None

    return {
        "hop":           hop,
        "ip":            ip,
        "latency_ms":    latency_ms,
        "min_ms":        min_ms,
        "max_ms":        max_ms,
        "is_timeout":    is_timeout,
        "is_bottleneck": False,
    }


def mark_bottlenecks(hops: List[dict], threshold_ms: int = 15) -> List[dict]:
    """
    Flag hops where the latency jump from the previous *responsive* hop exceeds
    *threshold_ms*.  Modifies each hop dict in-place and returns the list.

    Timeout hops are never flagged and do NOT advance the ``prev_ms`` baseline
    so that a run of timeouts in the middle of the trace doesn't mask a real
    bottleneck at the next responsive hop.

    The first responsive hop is never a bottleneck (no baseline to compare).
    """
    prev_ms: Optional[float] = None

    for hop in hops:
        if hop["is_timeout"] or hop["latency_ms"] is None:
            hop["is_bottleneck"] = False
            continue

        current_ms = hop["latency_ms"]

        if prev_ms is None:
            hop["is_bottleneck"] = False
        else:
            hop["is_bottleneck"] = (current_ms - prev_ms) > threshold_ms

        prev_ms = current_ms

    return hops


def discover_game_server(pid: int) -> Optional[str]:
    """
    Inspect the live network connections of process *pid* and return the first
    public remote IPv4/IPv6 address found.

    Requires admin rights (NetBoost always runs as admin).  Returns None if the
    process does not exist, access is denied, or all connections are private.
    """
    try:
        import psutil
        proc  = psutil.Process(pid)
        conns = proc.net_connections(kind="inet")
    except Exception as exc:
        logger.warning("route_analyzer: cannot read connections for PID %d: %s", pid, exc)
        return None

    for conn in conns:
        if conn.raddr and conn.raddr.ip:
            ip = conn.raddr.ip
            if not _is_private_ip(ip):
                logger.info("route_analyzer: detected server %s for PID %d", ip, pid)
                return ip

    logger.info("route_analyzer: no public remote IP found for PID %d", pid)
    return None


def trace_route(ip: str, max_hops: int = 30, timeout_ms: int = 2000) -> List[dict]:
    """
    Blocking synchronous tracert call — intended for tests or CLI use only.
    UI uses _TraceRouteWorker (streaming) instead.
    """
    cmd = ["tracert", "-d", "-h", str(max_hops), "-w", str(timeout_ms), ip]
    logger.info("route_analyzer.trace_route: %s", " ".join(cmd))
    hops: List[dict] = []

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max_hops * (timeout_ms / 1000.0) * 3 + 10,
        )
        for line in result.stdout.splitlines():
            hop = _parse_tracert_line(line)
            if hop:
                hops.append(hop)
    except subprocess.TimeoutExpired:
        logger.warning("route_analyzer.trace_route: timed out")
    except Exception as exc:
        logger.error("route_analyzer.trace_route: %s", exc)

    return mark_bottlenecks(hops)


# ── QRunnable workers (Qt dependency — imported lazily in run()) ──────────────

from PyQt5.QtCore import QRunnable, QObject, pyqtSignal  # noqa: E402


class _DiscoverWorkerSignals(QObject):
    found     = pyqtSignal(str)   # public IP string
    not_found = pyqtSignal()


class _DiscoverWorker(QRunnable):
    """
    Lightweight QRunnable that calls discover_game_server(pid) off the Qt thread
    and emits either found(ip) or not_found().
    """

    def __init__(self, signals: "_DiscoverWorkerSignals", pid: int):
        super().__init__()
        self.signals = signals
        self.pid     = pid
        self.setAutoDelete(True)

    def run(self) -> None:
        ip = discover_game_server(self.pid)
        if ip:
            self.signals.found.emit(ip)
        else:
            self.signals.not_found.emit()


class _TraceWorkerSignals(QObject):
    hop_found = pyqtSignal(dict)   # emitted per parsed hop while tracert runs
    finished  = pyqtSignal(list)   # complete annotated hop list
    error     = pyqtSignal(str)    # human-readable error string


class _TraceRouteWorker(QRunnable):
    """
    Streams ``tracert -d`` output line-by-line and emits hop_found for each
    parsed hop so the UI table populates live.  Emits finished with the full
    bottleneck-annotated list when done.

    Call cancel() to terminate the tracert subprocess mid-run.
    """

    def __init__(
        self,
        signals: "_TraceWorkerSignals",
        ip: str,
        max_hops: int = 30,
        timeout_ms: int = 2000,
        threshold_ms: int = 15,
    ):
        super().__init__()
        self.signals       = signals
        self.ip            = ip
        self.max_hops      = max_hops
        self.timeout_ms    = timeout_ms
        self.threshold_ms  = threshold_ms
        self._proc: Optional[subprocess.Popen] = None
        self._cancelled    = False
        self.setAutoDelete(True)

    def cancel(self) -> None:
        """Terminate the subprocess.  finished signal will NOT be emitted."""
        self._cancelled = True
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        cmd = [
            "tracert", "-d",
            "-h", str(self.max_hops),
            "-w", str(self.timeout_ms),
            self.ip,
        ]
        hops: List[dict] = []

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for raw_line in iter(self._proc.stdout.readline, ""):
                if self._cancelled:
                    break
                hop = _parse_tracert_line(raw_line)
                if hop:
                    hops.append(hop)
                    self.signals.hop_found.emit(dict(hop))

            self._proc.wait()

        except FileNotFoundError:
            self.signals.error.emit(
                "tracert not found — ensure Windows PATH includes System32."
            )
            return
        except Exception as exc:
            logger.error("_TraceRouteWorker: %s", exc)
            self.signals.error.emit(str(exc))
            return

        if self._cancelled:
            return

        mark_bottlenecks(hops, self.threshold_ms)
        self.signals.finished.emit(hops)
