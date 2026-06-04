"""
Stable-ping Game Mode policy.

This module keeps game-session defaults separate from the visible tab state.
Each supported game declares which Wi-Fi keys Game Mode should flip on when
that game is detected.

Both supported games are intentionally **Wi-Fi-only**: Game Mode auto-apply
never touches the FPS Booster, the Optimizer, or per-app QoS for them.  Those
levers stay manual (available in their tabs and in saved profiles) because the
goal of Stable Ping Mode is link-latency stability, not frame-rate or
background tuning — and the FPS/GPU/DSCP knobs were a recurring source of
stutter, thermal throttle, and confusion when applied automatically.

VALORANT applies only the 4-key Wi-Fi latency subset because Vanguard's kernel
anti-cheat mistrusts wider surfaces.  CS2 has no kernel driver, so it can use a
slightly wider Wi-Fi subset (adds ``disable_mimo_power_save`` and
``disable_bss_scan``), but it is still Wi-Fi-only by design.
"""

from __future__ import annotations

from core import setting_keys

STABLE_PING_GAME_EXES = frozenset({
    "valorant-win64-shipping.exe",
    "cs2.exe",
})

# ---------------------------------------------------------------------------
# Wi-Fi
# ---------------------------------------------------------------------------

# Canonical key tuples live in core/setting_keys.py — the single source of
# truth shared with settings_risk, the profile schema, and the UI tabs.
# Re-exported here under this module's historical names.
WIFI_SETTING_KEYS = setting_keys.WIFI_KEYS

# Valorant — minimum, Vanguard-safe.
VALORANT_WIFI_ENABLED_KEYS = frozenset({
    "disable_lso",
    "disable_interrupt_mod",
    "disable_power_saving",
    "max_tx_power",
})

# Backwards-compatible alias.  External callers (profile_manager,
# stable_ping_wifi_settings) treat this as the canonical "conservative"
# subset, which matches Valorant's needs.
STABLE_PING_WIFI_ENABLED_KEYS = VALORANT_WIFI_ENABLED_KEYS

# CS2 — Valorant subset plus two AX211-friendly keys Valorant deliberately
# omits: `disable_mimo_power_save` (keeps all MIMO chains hot) and
# `disable_bss_scan` (suppresses background channel scans).  No Vanguard
# concerns here.
#
# `disable_bss_scan` directly targets stable ping: background BSS/channel scans
# make the radio periodically leave its operating channel, producing recurring
# ~50-150 ms airtime gaps that surface as periodic in-game ping spikes.  A CS2
# match is a stationary, single-AP session, so there is no reason to scan
# mid-game (same rationale as `minimize_roaming`).  Rated LOW risk in
# core/settings_risk.py.
#
# `throughput_booster` is intentionally excluded: its packet-bursting behaviour
# competes with latency stability and was a confirmed source of in-game ping
# spikes for CS2 (see core/settings_risk.py — "Keep off for Stable Ping Mode").
# It stays available as a manual Wi-Fi toggle for users who want raw throughput.
CS2_WIFI_ENABLED_KEYS = frozenset(VALORANT_WIFI_ENABLED_KEYS | {
    "disable_mimo_power_save",
    "disable_bss_scan",
})

# ---------------------------------------------------------------------------
# Canonical key-group re-exports
# ---------------------------------------------------------------------------

# Game Mode no longer auto-applies any FPS or Optimizer keys for stable-ping
# games (both games are Wi-Fi-only).  These tuples are re-exported only so the
# setting_keys single-source-of-truth cross-checks and external callers keep a
# stable import path; they are not used to build any auto plan here.
FPS_SETTING_KEYS = setting_keys.FPS_KEYS
OPTIMIZER_SETTING_KEYS = setting_keys.OPTIMIZER_KEYS


# ---------------------------------------------------------------------------
# Predicates and dict-shape helpers
# ---------------------------------------------------------------------------

def is_stable_ping_game(exe_name: str | None) -> bool:
    """Return True when *exe_name* should use the stable-ping policy."""
    if not exe_name:
        return False
    return exe_name.lower() in STABLE_PING_GAME_EXES


def stable_ping_wifi_settings() -> dict[str, bool]:
    """Return the conservative Wi-Fi settings used by Valorant Stable Ping."""
    return {key: key in VALORANT_WIFI_ENABLED_KEYS for key in WIFI_SETTING_KEYS}


def cs2_wifi_settings() -> dict[str, bool]:
    """Return the CS2 Wi-Fi bundle (Valorant subset + MIMO / BSS-scan keys)."""
    return {key: key in CS2_WIFI_ENABLED_KEYS for key in WIFI_SETTING_KEYS}


# ---------------------------------------------------------------------------
# Plan builder
# ---------------------------------------------------------------------------

def build_game_mode_plan(
    exe_name: str | None,
    current_wifi: dict | None = None,
    current_fps: dict | None = None,
    current_optimizer: dict | None = None,
) -> dict[str, dict]:
    """
    Build the settings sections Game Mode should apply for *exe_name*.

    Stable-ping games get a Wi-Fi-only bundle (CS2 a slightly wider Wi-Fi
    subset than Valorant).  When no game is running, Game Mode stays armed and
    applies nothing.  Other detected games keep the legacy configured-tab
    behavior for compatibility.
    """
    if is_stable_ping_game(exe_name):
        if exe_name.lower() == "cs2.exe":
            return {"wifi": cs2_wifi_settings()}
        # Valorant and any other future conservative game.
        return {"wifi": stable_ping_wifi_settings()}

    if not exe_name:
        return {}

    plan: dict[str, dict] = {}
    if current_wifi is not None:
        plan["wifi"] = dict(current_wifi)
    if current_fps is not None:
        plan["fps"] = dict(current_fps)
    if current_optimizer is not None:
        plan["optimizer"] = dict(current_optimizer)
    return plan
