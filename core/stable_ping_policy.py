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

VALORANT and CS2 both apply the same conservative 4-key Wi-Fi latency subset.
The wider BSS-scan and MIMO power-save levers stay manual because they vary by
router/driver and can worsen jitter on some links.
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

# Conservative stable-ping subset.
VALORANT_WIFI_ENABLED_KEYS = frozenset({
    "disable_lso",
    "disable_interrupt_mod",
    "disable_power_saving",
    "max_tx_power",
})

# Backwards-compatible alias. External callers (profile_manager,
# stable_ping_wifi_settings) treat this as the canonical conservative subset.
STABLE_PING_WIFI_ENABLED_KEYS = VALORANT_WIFI_ENABLED_KEYS

# CS2 uses the same lighter default. BSS scan and MIMO power-save changes are
# still available as manual Wi-Fi toggles for one-at-a-time troubleshooting, but
# they are no longer part of the auto-applied CS2 profile.
#
# `throughput_booster` remains excluded: its packet-bursting behavior competes
# with latency stability and can create in-game ping spikes.
CS2_WIFI_ENABLED_KEYS = STABLE_PING_WIFI_ENABLED_KEYS

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
    """Return the conservative stable-ping Wi-Fi settings."""
    return {key: key in VALORANT_WIFI_ENABLED_KEYS for key in WIFI_SETTING_KEYS}


def cs2_wifi_settings() -> dict[str, bool]:
    """Return the lighter CS2 Wi-Fi bundle."""
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

    Stable-ping games get a conservative Wi-Fi-only bundle. When no game is
    running, Game Mode stays armed and applies nothing. Other detected games
    keep the legacy configured-tab behavior for compatibility.
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
