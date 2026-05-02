"""
Unit tests for core.route_analyzer pure functions.

The QRunnable workers (_TraceRouteWorker, _DiscoverWorker) are intentionally
out of scope here — they are integration concerns covered by the live route tab.
"""

import subprocess
from unittest.mock import MagicMock

import pytest

from core import route_analyzer


# ── _is_private_ip ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.42",
        "127.0.0.1",
        "169.254.1.1",
        "::1",
        "fe80::1",
        "fc00::1",
    ],
)
def test_is_private_ip_true_for_non_routable(ip):
    assert route_analyzer._is_private_ip(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "9.9.9.9", "2001:4860:4860::8888"])
def test_is_private_ip_false_for_public(ip):
    assert route_analyzer._is_private_ip(ip) is False


def test_is_private_ip_treats_garbage_as_non_routable():
    assert route_analyzer._is_private_ip("not-an-ip") is True
    assert route_analyzer._is_private_ip("") is True


# ── _parse_ms ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "token, expected",
    [
        ("<1 ms", 0.5),
        ("5 ms", 5.0),
        ("12 ms", 12.0),
        ("  37 ms  ", 37.0),
        ("*", None),
        ("", None),
        ("garbage", None),
    ],
)
def test_parse_ms(token, expected):
    assert route_analyzer._parse_ms(token) == expected


# ── _parse_tracert_line ───────────────────────────────────────────────────────

def test_parse_tracert_line_happy_path():
    line = "  3    12 ms    11 ms    13 ms  203.0.113.7"
    hop = route_analyzer._parse_tracert_line(line)

    assert hop is not None
    assert hop["hop"] == 3
    assert hop["ip"] == "203.0.113.7"
    assert hop["latency_ms"] == pytest.approx(12.0)
    assert hop["min_ms"] == 11.0
    assert hop["max_ms"] == 13.0
    assert hop["is_timeout"] is False
    assert hop["is_bottleneck"] is False


def test_parse_tracert_line_all_timeout():
    line = "  4     *        *        *     Request timed out."
    hop = route_analyzer._parse_tracert_line(line)

    assert hop is not None
    assert hop["hop"] == 4
    assert hop["ip"] is None
    assert hop["latency_ms"] is None
    assert hop["min_ms"] is None
    assert hop["max_ms"] is None
    assert hop["is_timeout"] is True


def test_parse_tracert_line_partial_timeout_keeps_responding_probes():
    line = "  5    20 ms    *        18 ms  198.51.100.4"
    hop = route_analyzer._parse_tracert_line(line)

    assert hop is not None
    assert hop["is_timeout"] is False
    assert hop["ip"] == "198.51.100.4"
    assert hop["latency_ms"] == pytest.approx(19.0)
    assert hop["min_ms"] == 18.0
    assert hop["max_ms"] == 20.0


def test_parse_tracert_line_returns_none_on_header_or_blank():
    assert route_analyzer._parse_tracert_line("") is None
    assert route_analyzer._parse_tracert_line(
        "Tracing route to 1.1.1.1 over a maximum of 30 hops"
    ) is None


def test_parse_tracert_line_skips_ip_when_rest_is_hostname():
    line = "  6    25 ms    24 ms    26 ms  some-router.isp.example"
    hop = route_analyzer._parse_tracert_line(line)

    assert hop is not None
    assert hop["ip"] is None  # rest is not a parseable IP — leave None
    assert hop["latency_ms"] == pytest.approx(25.0)


# ── mark_bottlenecks ──────────────────────────────────────────────────────────

def _make_hop(hop, latency, is_timeout=False):
    return {
        "hop": hop,
        "ip": None if is_timeout else f"203.0.113.{hop}",
        "latency_ms": None if is_timeout else latency,
        "min_ms": None if is_timeout else latency,
        "max_ms": None if is_timeout else latency,
        "is_timeout": is_timeout,
        "is_bottleneck": False,
    }


def test_mark_bottlenecks_flags_jump_above_threshold():
    hops = [_make_hop(1, 5), _make_hop(2, 8), _make_hop(3, 30), _make_hop(4, 32)]
    route_analyzer.mark_bottlenecks(hops, threshold_ms=15)

    assert hops[0]["is_bottleneck"] is False  # first responsive hop never flagged
    assert hops[1]["is_bottleneck"] is False  # 8-5=3 ms jump
    assert hops[2]["is_bottleneck"] is True   # 30-8=22 ms jump (>15)
    assert hops[3]["is_bottleneck"] is False  # 32-30=2 ms jump


def test_mark_bottlenecks_does_not_flag_first_responsive_hop():
    hops = [_make_hop(1, 200)]  # huge first hop, no baseline to compare
    route_analyzer.mark_bottlenecks(hops, threshold_ms=15)
    assert hops[0]["is_bottleneck"] is False


def test_mark_bottlenecks_timeouts_do_not_advance_baseline():
    # Baseline 5 ms, then two timeouts, then 30 ms — must still flag the 30 ms hop
    hops = [
        _make_hop(1, 5),
        _make_hop(2, 0, is_timeout=True),
        _make_hop(3, 0, is_timeout=True),
        _make_hop(4, 30),
    ]
    route_analyzer.mark_bottlenecks(hops, threshold_ms=15)

    assert hops[1]["is_bottleneck"] is False
    assert hops[2]["is_bottleneck"] is False
    assert hops[3]["is_bottleneck"] is True


def test_mark_bottlenecks_returns_input_list():
    hops = [_make_hop(1, 5)]
    result = route_analyzer.mark_bottlenecks(hops)
    assert result is hops  # in-place mutation, identity preserved


# ── discover_game_server ──────────────────────────────────────────────────────

def _conn(remote_ip):
    c = MagicMock()
    c.raddr = MagicMock()
    c.raddr.ip = remote_ip
    return c


def test_discover_game_server_returns_first_public_ip(monkeypatch):
    proc = MagicMock()
    proc.net_connections.return_value = [
        _conn("192.168.1.1"),     # private — skip
        _conn("10.0.0.5"),         # private — skip
        _conn("8.8.8.8"),          # public — pick this
        _conn("1.1.1.1"),          # later public — ignored
    ]
    fake_psutil = MagicMock()
    fake_psutil.Process.return_value = proc
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)

    assert route_analyzer.discover_game_server(1234) == "8.8.8.8"


def test_discover_game_server_returns_none_when_all_private(monkeypatch):
    proc = MagicMock()
    proc.net_connections.return_value = [_conn("192.168.1.5"), _conn("10.0.0.7")]
    fake_psutil = MagicMock()
    fake_psutil.Process.return_value = proc
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)

    assert route_analyzer.discover_game_server(1234) is None


def test_discover_game_server_returns_none_on_psutil_error(monkeypatch):
    fake_psutil = MagicMock()
    fake_psutil.Process.side_effect = Exception("NoSuchProcess(1234)")
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)

    assert route_analyzer.discover_game_server(1234) is None


def test_discover_game_server_skips_connections_without_raddr(monkeypatch):
    bad = MagicMock()
    bad.raddr = None
    public = _conn("9.9.9.9")
    proc = MagicMock()
    proc.net_connections.return_value = [bad, public]
    fake_psutil = MagicMock()
    fake_psutil.Process.return_value = proc
    monkeypatch.setitem(__import__("sys").modules, "psutil", fake_psutil)

    assert route_analyzer.discover_game_server(1234) == "9.9.9.9"


# ── trace_route (synchronous, mocked subprocess) ──────────────────────────────

_SAMPLE_TRACERT = """\
Tracing route to 1.1.1.1 over a maximum of 30 hops

  1    <1 ms    <1 ms    <1 ms  192.168.1.1
  2     5 ms     4 ms     5 ms  10.0.0.1
  3    25 ms    24 ms    26 ms  203.0.113.1
  4     *        *        *     Request timed out.
  5    50 ms    49 ms    51 ms  198.51.100.7

Trace complete.
"""


def test_trace_route_parses_and_marks_bottlenecks(monkeypatch):
    fake_result = MagicMock()
    fake_result.stdout = _SAMPLE_TRACERT
    monkeypatch.setattr(route_analyzer.subprocess, "run", lambda *a, **kw: fake_result)

    hops = route_analyzer.trace_route("1.1.1.1")

    assert [h["hop"] for h in hops] == [1, 2, 3, 4, 5]
    assert hops[0]["latency_ms"] == 0.5
    assert hops[3]["is_timeout"] is True
    # Hop 3: 25 - 5 = 20 ms jump > 15 ms threshold → bottleneck
    assert hops[2]["is_bottleneck"] is True
    # Hop 5: prev responsive baseline is hop 3 (25 ms), 50-25=25 ms → bottleneck
    assert hops[4]["is_bottleneck"] is True


def test_trace_route_handles_subprocess_timeout(monkeypatch):
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="tracert", timeout=10)

    monkeypatch.setattr(route_analyzer.subprocess, "run", boom)

    hops = route_analyzer.trace_route("1.1.1.1")
    assert hops == []  # graceful empty list, no crash
