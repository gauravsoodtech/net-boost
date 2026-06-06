"""
core/network_diagnostics.py
Honest, leg-by-leg network diagnostic for NetBoost.

NetBoost's Wi-Fi registry tweaks cannot fix latency that is added *on the path
to the game server* — only latency on the local Wi-Fi link.  This module
measures each leg of the path separately:

    you ── router (gateway) ── ISP edge (1.1.1.1) ── game server

and produces a plain-English verdict telling the user where the latency comes
from and whether any local action (or NetBoost itself) can help.

Pure logic only — no Qt.  All system access goes through ``subprocess`` /
``route_analyzer`` so the whole module is unit-testable with mocks.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import subprocess
from statistics import stdev
from typing import List, Optional

from core import route_analyzer

logger = logging.getLogger(__name__)

# Internet edge target used as the "ISP first mile" reference leg.
EDGE_HOST = "1.1.1.1"

# Classification thresholds (milliseconds / percent).  Tuned for Wi-Fi gaming:
# a healthy router ping is single-digit ms; the edge is usually <40 ms.
GATEWAY_BAD_MS = 30.0
GATEWAY_JITTER_MS = 15.0
EDGE_BAD_MS = 60.0
EDGE_JITTER_MS = 15.0
SERVER_BAD_MS = 80.0
LOSS_BAD_PCT = 5.0

# Shared "time=XXms" / "time<1ms" matcher for Windows ping.exe replies.
_PING_TIME_RE = re.compile(r"time[=<]\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)
_PING_SUBMS_RE = re.compile(r"time<1\s*ms", re.IGNORECASE)
_PING_LOSS_RE = re.compile(r"\((\d+(?:\.\d+)?)%\s*loss\)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------

def _empty_ping_result(host: str) -> dict:
    return {
        "host": host,
        "reachable": False,
        "avg_ms": None,
        "min_ms": None,
        "max_ms": None,
        "jitter_ms": None,
        "loss_pct": 100.0,
        "samples": [],
    }


def parse_ping_stats(host: str, stdout: str) -> dict:
    """
    Parse Windows ``ping.exe`` output into a stats dict.

    Returns ``{host, reachable, avg_ms, min_ms, max_ms, jitter_ms, loss_pct,
    samples}``.  ``reachable`` is True when at least one reply was received.
    Jitter is the standard deviation of the per-reply round-trip times.
    """
    result = _empty_ping_result(host)

    samples: List[float] = []
    for line in stdout.splitlines():
        if _PING_SUBMS_RE.search(line):
            samples.append(0.5)
            continue
        m = _PING_TIME_RE.search(line)
        if m:
            samples.append(float(m.group(1)))

    loss_match = _PING_LOSS_RE.search(stdout)
    if loss_match:
        result["loss_pct"] = float(loss_match.group(1))

    if samples:
        result["reachable"] = True
        result["samples"] = samples
        result["avg_ms"] = round(sum(samples) / len(samples), 1)
        result["min_ms"] = round(min(samples), 1)
        result["max_ms"] = round(max(samples), 1)
        result["jitter_ms"] = round(stdev(samples), 1) if len(samples) > 1 else 0.0
        if not loss_match:
            result["loss_pct"] = 0.0

    return result


def ping_target(host: str, count: int = 10, timeout_ms: int = 2000) -> dict:
    """
    Ping *host* *count* times and return parsed stats (see :func:`parse_ping_stats`).

    Never raises — a failed launch or timeout returns an unreachable result.
    """
    if not host:
        return _empty_ping_result(host)

    try:
        proc = subprocess.run(
            ["ping", "-n", str(count), "-w", str(timeout_ms), host],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=count * (timeout_ms / 1000.0) + 10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("network_diagnostics: ping %s failed: %s", host, exc)
        return _empty_ping_result(host)

    return parse_ping_stats(host, proc.stdout or "")


# ---------------------------------------------------------------------------
# Default gateway (first hop / router)
# ---------------------------------------------------------------------------

def parse_gateway_from_route_print(stdout: str) -> Optional[str]:
    """
    Parse the active default-route gateway from ``route print -4`` output.

    Default routes look like::

        0.0.0.0          0.0.0.0      192.168.1.1     192.168.1.20     35

    Columns are: destination, netmask, gateway, interface, metric.  When more
    than one default route exists, the one with the lowest metric wins.  Rows
    with an on-link gateway (``0.0.0.0``) are skipped.  Returns the gateway IP
    string or ``None``.
    """
    best_ip: Optional[str] = None
    best_metric = float("inf")

    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        if parts[0] != "0.0.0.0" or parts[1] != "0.0.0.0":
            continue

        gateway = parts[2]
        if gateway == "0.0.0.0":
            continue
        try:
            ipaddress.ip_address(gateway)
        except ValueError:
            continue

        try:
            metric = float(parts[4]) if len(parts) >= 5 else 0.0
        except ValueError:
            metric = 0.0

        if metric < best_metric:
            best_metric = metric
            best_ip = gateway

    return best_ip


def get_default_gateway() -> Optional[str]:
    """
    Return the active IPv4 default-gateway IP, or ``None`` if undeterminable.
    """
    try:
        proc = subprocess.run(
            ["route", "print", "-4"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("network_diagnostics: route print failed: %s", exc)
        return None

    return parse_gateway_from_route_print(proc.stdout or "")


# ---------------------------------------------------------------------------
# Game server discovery
# ---------------------------------------------------------------------------

def parse_netstat_remote_ips(stdout: str) -> List[str]:
    """
    Return public remote IPs from ESTABLISHED connections in ``netstat -n``
    output, in first-seen order, de-duplicated.

    UDP rows have no foreign endpoint and are ignored — this only finds TCP
    control channels, so Vanguard-protected UDP games may still yield nothing
    (handled by the caller / verdict).
    """
    found: List[str] = []
    seen = set()
    for line in stdout.splitlines():
        parts = line.split()
        # Layout: Proto  Local Address  Foreign Address  State
        if len(parts) < 4:
            continue
        if parts[0].upper() != "TCP":
            continue
        if parts[3].upper() != "ESTABLISHED":
            continue

        foreign = parts[2]
        # Strip the :port suffix (IPv4 "1.2.3.4:443"; IPv6 "[::1]:443").
        if foreign.startswith("["):
            host = foreign[1:].split("]")[0]
        else:
            host = foreign.rsplit(":", 1)[0]

        if route_analyzer._is_private_ip(host):
            continue
        if host in seen:
            continue
        seen.add(host)
        found.append(host)

    return found


def find_active_server_ip(pid: Optional[int] = None) -> Optional[str]:
    """
    Best-effort discovery of the current game server IP.

    Tries the per-process connection scan first (``route_analyzer`` —
    accurate when the game's connections are visible), then falls back to a
    system-wide ``netstat`` scan for the first public remote endpoint.

    Returns the IP string or ``None`` when it cannot be determined (common for
    Vanguard-protected UDP titles — the UI then asks for manual entry).
    """
    if pid:
        ip = route_analyzer.discover_game_server(pid)
        if ip:
            return ip

    try:
        proc = subprocess.run(
            ["netstat", "-n"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        logger.warning("network_diagnostics: netstat failed: %s", exc)
        return None

    ips = parse_netstat_remote_ips(proc.stdout or "")
    return ips[0] if ips else None


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------

def _leg_label(res: dict) -> str:
    """One-line human summary of a ping leg."""
    if not res or not res.get("reachable"):
        return "unreachable"
    avg = res.get("avg_ms")
    jit = res.get("jitter_ms") or 0.0
    loss = res.get("loss_pct") or 0.0
    out = f"{avg:.0f} ms (jitter {jit:.0f} ms"
    if loss:
        out += f", {loss:.0f}% loss"
    return out + ")"


def _bottleneck_summary(hops: List[dict]) -> Optional[str]:
    """Describe the first bottleneck hop, or None when there is none."""
    if not hops:
        return None
    prev_ms = None
    for h in hops:
        if h.get("is_timeout") or h.get("latency_ms") is None:
            continue
        if h.get("is_bottleneck") and prev_ms is not None:
            jump = h["latency_ms"] - prev_ms
            where = h.get("ip") or "an upstream hop"
            return f"hop {h['hop']} ({where}, +{jump:.0f} ms)"
        prev_ms = h["latency_ms"]
    return None


def build_verdict(
    gateway_res: Optional[dict],
    edge_res: Optional[dict],
    server_res: Optional[dict],
    hops: Optional[List[dict]] = None,
) -> str:
    """
    Classify the three measured legs into a plain-English verdict.

    Each ``*_res`` is a :func:`ping_target` result dict (or ``None`` if that
    leg was skipped).  *hops* is the traceroute hop list from
    ``route_analyzer`` (used to localize a server-path bottleneck).
    """
    hops = hops or []

    def _clean(res, avg_max: float, jit_max: float) -> bool:
        return bool(
            res and res.get("reachable")
            and (res.get("avg_ms") or 0) <= avg_max
            and (res.get("jitter_ms") or 0) <= jit_max
            and (res.get("loss_pct") or 0) <= LOSS_BAD_PCT
        )

    gw_ok = bool(gateway_res and gateway_res.get("reachable"))
    edge_ok = bool(edge_res and edge_res.get("reachable"))
    server_ok = bool(server_res and server_res.get("reachable"))

    # The edge leg (1.1.1.1) crosses the SAME Wi-Fi link as everything else and
    # is a steady, reliable ICMP responder, so it -- not the router's own ping --
    # is the trustworthy proxy for local link health.  Home routers routinely
    # deprioritize ICMP to their own management IP (answering it on a slow path),
    # so a high/jittery gateway reading alongside a clean edge does NOT mean the
    # Wi-Fi is bad.  We therefore treat the gateway only as a *supporting* signal:
    # a clean gateway is trustworthy, an inflated one is not.
    edge_clean = _clean(edge_res, EDGE_BAD_MS, EDGE_JITTER_MS)
    edge_bad = edge_ok and not edge_clean
    gw_clean = _clean(gateway_res, GATEWAY_BAD_MS, GATEWAY_JITTER_MS)

    server_bad = server_ok and (
        (server_res["avg_ms"] or 0) > SERVER_BAD_MS
        or (server_res.get("loss_pct") or 0) > LOSS_BAD_PCT
    )

    # --- No usable internet path ---
    if not edge_ok:
        if gw_ok:
            return (
                "Your router answers but the internet (1.1.1.1) is unreachable. "
                "That's your modem/ISP being down or a DNS/outage issue -- not "
                "your PC or NetBoost."
            )
        return (
            "No connectivity -- couldn't reach your router or the internet. "
            "Check that Wi-Fi is actually connected."
        )

    # --- The link out to the internet is unstable (a real local problem) ---
    if edge_bad:
        if gw_clean:
            return (
                f"The hop from your router out to the internet is unstable "
                f"(1.1.1.1 = {_leg_label(edge_res)}) while the router itself is "
                f"fine ({_leg_label(gateway_res)}). That points at your ISP's "
                f"first mile / line, not your PC or NetBoost. Restart the router "
                f"and raise it with your ISP if it persists."
            )
        return (
            f"Your connection to the internet is unstable -- ping to 1.1.1.1 is "
            f"{_leg_label(edge_res)}, and it crosses your Wi-Fi link. This is "
            f"your local Wi-Fi: move closer to the router, cut 2.4GHz congestion "
            f"(microwave / neighbours / Bluetooth), or try 5GHz. This is the one "
            f"part NetBoost's Wi-Fi tab can sometimes help with."
        )

    # --- Local legs are healthy (edge is clean). The router's own ping may read
    #     high here; that's normal ICMP deprioritization, not a fault, because
    #     the clean edge proves the link itself is fine. ---
    healthy = (
        f"Your Wi-Fi link and internet connection are healthy "
        f"(1.1.1.1 = {_leg_label(edge_res)})"
    )
    bottleneck = _bottleneck_summary(hops)

    if server_bad or bottleneck:
        head = healthy + "."
        if server_ok:
            head += f" The game server is {_leg_label(server_res)}."
        where = (
            f" The latency is added at {bottleneck}."
            if bottleneck
            else " The latency is on the route to the server."
        )
        return (
            head + where + " This is the path to the game server -- NOT "
            "something NetBoost or any local setting can fix. Pick a closer "
            "in-game server region if you can; if the region is already correct, "
            "it's a distant server or an ISP routing/peering issue."
        )

    if not server_ok:
        return (
            healthy + ". Couldn't measure the game server (its address wasn't "
            "found -- common for Vanguard-protected games that hide their UDP "
            "connections). Enter the server IP manually and run again. If 1.1.1.1 "
            "is fine but the game isn't, the lag is the route to the server, "
            "which NetBoost cannot tune."
        )

    # --- Everything measured fine ---
    return (
        healthy
        + (f", server {_leg_label(server_res)}" if server_ok else "")
        + ". If the game still spikes it's likely brief bufferbloat from "
        "background apps (big downloads / updates) saturating the link -- close "
        "them during play. A Wi-Fi registry tweak won't fix that."
    )
