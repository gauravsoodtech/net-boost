"""
Stable-ping Game Mode policy.

This module keeps game-session defaults separate from the visible tab state.

Supported stable-ping games are monitoring-only by default: Game Mode
auto-apply never touches Wi-Fi registry values, the FPS Booster, the Optimizer,
or per-app QoS for them. Those levers stay manual because applying driver-level
Wi-Fi settings automatically can destabilize some Intel adapter / router
combinations and force a network reset.

VALORANT and CS2 both use the same empty auto-apply surface. The Wi-Fi tab can
still be used manually for one-at-a-time troubleshooting.
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

# Canonical key tuples live in core/setting_keys.py - the single source of
# truth shared with settings_risk, the profile schema, and the UI tabs.
# Re-exported here under this module's historical names.
WIFI_SETTING_KEYS = setting_keys.WIFI_KEYS

# Stable-ping Game Mode does not automatically write Wi-Fi driver settings.
VALORANT_WIFI_ENABLED_KEYS = frozenset()

# Backwards-compatible alias. External callers (profile_manager,
# stable_ping_wifi_settings) treat this as the canonical stable-ping subset.
STABLE_PING_WIFI_ENABLED_KEYS = VALORANT_WIFI_ENABLED_KEYS

# CS2 uses the same monitoring-only default. BSS scan, MIMO power save,
# throughput booster, LSO, interrupt moderation, and power settings remain
# manual Wi-Fi toggles.
CS2_WIFI_ENABLED_KEYS = STABLE_PING_WIFI_ENABLED_KEYS

# ---------------------------------------------------------------------------
# Canonical key-group re-exports
# ---------------------------------------------------------------------------

# Game Mode no longer auto-applies any FPS or Optimizer keys for stable-ping
# games. These tuples are re-exported only so the setting_keys
# single-source-of-truth cross-checks and external callers keep a stable import
# path; they are not used to build any auto plan here.
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
    """Return the stable-ping Wi-Fi settings."""
    return {key: key in VALORANT_WIFI_ENABLED_KEYS for key in WIFI_SETTING_KEYS}


def cs2_wifi_settings() -> dict[str, bool]:
    """Return the CS2 Wi-Fi settings."""
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

    Stable-ping games are monitoring-only and apply nothing automatically.
    When no game is running, Game Mode stays armed and applies nothing. Other
    detected games keep the legacy configured-tab behavior for compatibility.
    """
    if is_stable_ping_game(exe_name):
        return {}

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
