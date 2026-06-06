"""
Unit tests for core.network_diagnostics.

All system access (ping, route, netstat, psutil) is mocked — no real network
or hardware is touched.
"""

import subprocess
from unittest.mock import MagicMock

import pytest

from core import network_diagnostics as nd


# ── parse_ping_stats ──────────────────────────────────────────────────────────

_PING_OK = """\
Pinging 1.1.1.1 with 32 bytes of data:
Reply from 1.1.1.1: bytes=32 time=12ms TTL=57
Reply from 1.1.1.1: bytes=32 time=14ms TTL=57
Reply from 1.1.1.1: bytes=32 time=11ms TTL=57

Ping statistics for 1.1.1.1:
    Packets: Sent = 3, Received = 3, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 11ms, Maximum = 14ms, Average = 12ms
"""

_PING_ALL_LOST = """\
Pinging 203.0.113.9 with 32 bytes of data:
Request timed out.
Request timed out.

Ping statistics for 203.0.113.9:
    Packets: Sent = 2, Received = 0, Lost = 2 (100% loss),
"""

_PING_SUBMS = """\
Reply from 192.168.1.1: bytes=32 time<1ms TTL=64
Reply from 192.168.1.1: bytes=32 time<1ms TTL=64
    Packets: Sent = 2, Received = 2, Lost = 0 (0% loss),
"""


def test_parse_ping_stats_happy_path():
    res = nd.parse_ping_stats("1.1.1.1", _PING_OK)
    assert res["reachable"] is True
    assert res["samples"] == [12.0, 14.0, 11.0]
    assert res["avg_ms"] == pytest.approx(12.3, abs=0.1)
    assert res["min_ms"] == 11.0
    assert res["max_ms"] == 14.0
    assert res["jitter_ms"] > 0
    assert res["loss_pct"] == 0.0


def test_parse_ping_stats_total_loss():
    res = nd.parse_ping_stats("203.0.113.9", _PING_ALL_LOST)
    assert res["reachable"] is False
    assert res["avg_ms"] is None
    assert res["loss_pct"] == 100.0


def test_parse_ping_stats_sub_millisecond():
    res = nd.parse_ping_stats("192.168.1.1", _PING_SUBMS)
    assert res["reachable"] is True
    assert res["samples"] == [0.5, 0.5]
    assert res["avg_ms"] == 0.5
    assert res["jitter_ms"] == 0.0  # identical samples → zero stdev


# ── ping_target ───────────────────────────────────────────────────────────────

def test_ping_target_parses_subprocess_output(monkeypatch):
    fake = MagicMock()
    fake.stdout = _PING_OK
    monkeypatch.setattr(nd.subprocess, "run", lambda *a, **kw: fake)

    res = nd.ping_target("1.1.1.1", count=3)
    assert res["reachable"] is True
    assert res["avg_ms"] == pytest.approx(12.3, abs=0.1)


def test_ping_target_empty_host_is_unreachable():
    res = nd.ping_target("")
    assert res["reachable"] is False
    assert res["loss_pct"] == 100.0


def test_ping_target_handles_timeout(monkeypatch):
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="ping", timeout=5)

    monkeypatch.setattr(nd.subprocess, "run", boom)
    res = nd.ping_target("1.1.1.1")
    assert res["reachable"] is False


# ── parse_gateway_from_route_print ────────────────────────────────────────────

_ROUTE_PRINT = """\
===========================================================================
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.20     50
          0.0.0.0          0.0.0.0      192.168.0.254   192.168.0.20     25
        127.0.0.0        255.0.0.0         On-link         127.0.0.1    331
===========================================================================
"""

_ROUTE_PRINT_ONLINK_ONLY = """\
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0         0.0.0.0       10.0.0.5        25
"""


def test_parse_gateway_picks_lowest_metric():
    # Two default routes; metric 25 (192.168.0.254) beats metric 50.
    assert nd.parse_gateway_from_route_print(_ROUTE_PRINT) == "192.168.0.254"


def test_parse_gateway_skips_onlink_default_route():
    assert nd.parse_gateway_from_route_print(_ROUTE_PRINT_ONLINK_ONLY) is None


def test_parse_gateway_returns_none_when_no_default_route():
    assert nd.parse_gateway_from_route_print("no routes here") is None


def test_get_default_gateway_uses_route_print(monkeypatch):
    fake = MagicMock()
    fake.stdout = _ROUTE_PRINT
    monkeypatch.setattr(nd.subprocess, "run", lambda *a, **kw: fake)
    assert nd.get_default_gateway() == "192.168.0.254"


def test_get_default_gateway_handles_failure(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("route")

    monkeypatch.setattr(nd.subprocess, "run", boom)
    assert nd.get_default_gateway() is None


# ── parse_netstat_remote_ips ──────────────────────────────────────────────────

_NETSTAT = """\
Active Connections

  Proto  Local Address          Foreign Address        State
  TCP    192.168.1.20:50314     8.8.8.8:443            ESTABLISHED
  TCP    192.168.1.20:50315     192.168.1.5:445        ESTABLISHED
  TCP    192.168.1.20:50316     9.9.9.9:443            ESTABLISHED
  TCP    192.168.1.20:50317     9.9.9.9:8443           ESTABLISHED
  TCP    127.0.0.1:50318        127.0.0.1:1234         ESTABLISHED
  TCP    192.168.1.20:50319     1.1.1.1:443            TIME_WAIT
  UDP    192.168.1.20:50320     *:*
"""


def test_parse_netstat_remote_ips_public_established_only():
    ips = nd.parse_netstat_remote_ips(_NETSTAT)
    # 8.8.8.8 first, 9.9.9.9 deduped, private/loopback/TIME_WAIT/UDP excluded.
    assert ips == ["8.8.8.8", "9.9.9.9"]


def test_parse_netstat_remote_ips_empty():
    assert nd.parse_netstat_remote_ips("nothing useful") == []


# ── find_active_server_ip ─────────────────────────────────────────────────────

def test_find_active_server_ip_prefers_process_scan(monkeypatch):
    monkeypatch.setattr(nd.route_analyzer, "discover_game_server", lambda pid: "203.0.113.7")
    # subprocess must NOT be consulted when the process scan succeeds.
    monkeypatch.setattr(nd.subprocess, "run", lambda *a, **kw: pytest.fail("netstat called"))
    assert nd.find_active_server_ip(1234) == "203.0.113.7"


def test_find_active_server_ip_falls_back_to_netstat(monkeypatch):
    monkeypatch.setattr(nd.route_analyzer, "discover_game_server", lambda pid: None)
    fake = MagicMock()
    fake.stdout = _NETSTAT
    monkeypatch.setattr(nd.subprocess, "run", lambda *a, **kw: fake)
    assert nd.find_active_server_ip(1234) == "8.8.8.8"


def test_find_active_server_ip_returns_none_when_nothing_found(monkeypatch):
    monkeypatch.setattr(nd.route_analyzer, "discover_game_server", lambda pid: None)
    fake = MagicMock()
    fake.stdout = "Active Connections\n"
    monkeypatch.setattr(nd.subprocess, "run", lambda *a, **kw: fake)
    assert nd.find_active_server_ip(None) is None


# ── build_verdict ─────────────────────────────────────────────────────────────

def _ping(avg, jitter=1.0, loss=0.0, reachable=True):
    return {
        "host": "x",
        "reachable": reachable,
        "avg_ms": avg if reachable else None,
        "min_ms": avg,
        "max_ms": avg,
        "jitter_ms": jitter,
        "loss_pct": loss,
        "samples": [avg] if reachable else [],
    }


def _hop(hop, latency, bottleneck=False, ip=None, timeout=False):
    return {
        "hop": hop,
        "ip": ip,
        "latency_ms": None if timeout else latency,
        "min_ms": None if timeout else latency,
        "max_ms": None if timeout else latency,
        "is_timeout": timeout,
        "is_bottleneck": bottleneck,
    }


def test_verdict_blames_wifi_when_gateway_is_bad():
    v = nd.build_verdict(_ping(60, jitter=25), _ping(20), _ping(210), [])
    assert "router" in v.lower()
    assert "wi-fi" in v.lower()


def test_verdict_blames_isp_when_edge_is_bad_but_gateway_fine():
    v = nd.build_verdict(_ping(3), _ping(120), _ping(210), [])
    assert "isp" in v.lower()
    assert "first mile" in v.lower()


def test_verdict_blames_server_path_with_bottleneck():
    hops = [_hop(1, 3, ip="192.168.1.1"), _hop(2, 8), _hop(3, 200, bottleneck=True, ip="203.0.113.9")]
    v = nd.build_verdict(_ping(3), _ping(20), _ping(210), hops)
    assert "path to the game server" in v.lower()
    assert "hop 3" in v.lower()
    assert "netboost" in v.lower()  # explicitly says NetBoost cannot fix it


def test_verdict_when_server_not_found():
    v = nd.build_verdict(_ping(3), _ping(20), None, [])
    assert "couldn't measure the game server" in v.lower()
    assert "manually" in v.lower()


def test_verdict_when_everything_healthy_mentions_bufferbloat():
    v = nd.build_verdict(_ping(3), _ping(18), _ping(30), [])
    assert "bufferbloat" in v.lower()


def test_verdict_server_bad_without_bottleneck_still_blames_path():
    # No traceroute hops, but the server ping itself is high.
    v = nd.build_verdict(_ping(3), _ping(20), _ping(210), [])
    assert "route to the server" in v.lower()


# ── helper coverage ───────────────────────────────────────────────────────────

def test_leg_label_unreachable_and_loss():
    assert nd._leg_label(None) == "unreachable"
    assert nd._leg_label(_ping(0, reachable=False)) == "unreachable"
    assert "% loss" in nd._leg_label(_ping(20, loss=8.0))


def test_bottleneck_summary_skips_timeouts_and_returns_none_when_clean():
    assert nd._bottleneck_summary([]) is None
    clean = [_hop(1, 3), _hop(2, 5), _hop(3, 0, timeout=True)]
    assert nd._bottleneck_summary(clean) is None


def test_parse_ping_stats_single_sample_zero_jitter():
    res = nd.parse_ping_stats("x", "Reply from x: time=9ms TTL=64")
    assert res["samples"] == [9.0]
    assert res["jitter_ms"] == 0.0


def test_find_active_server_ip_handles_netstat_failure(monkeypatch):
    monkeypatch.setattr(nd.route_analyzer, "discover_game_server", lambda pid: None)

    def boom(*a, **kw):
        raise OSError("netstat unavailable")

    monkeypatch.setattr(nd.subprocess, "run", boom)
    assert nd.find_active_server_ip(999) is None
