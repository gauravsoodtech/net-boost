"""
Stable-ping Game Mode policy.

This module keeps game-session defaults separate from the visible tab state.
Each supported game declares which Wi-Fi / FPS / Optimizer keys Game Mode
should flip on when that game is detected.

VALORANT is deliberately conservative: only the 4-key Wi-Fi latency subset is
applied automatically because Vanguard's kernel anti-cheat mistrusts wider
surfaces.  CS2 has no such constraint (pure UDP, no kernel driver), so its
auto plan includes the stutter-prevention FPS bundle and the
background-bandwidth Optimizer bundle in addition to a slightly wider Wi-Fi
subset and a per-app DSCP EF (46) QoS policy.
"""

from __future__ import annotations

from core import setting_keys

STABLE_PING_GAME_EXES = frozenset({
    "valorant-win64-shipping.exe",
    "cs2.exe",
})

# Games that additionally benefit from a per-app DSCP EF (46) QoS policy on
# their executable.  Valorant is intentionally excluded — Vanguard's kernel
# driver interferes with QoS hooks.  CS2 is pure UDP and has no anti-cheat
# surface to worry about.
DSCP_GAME_EXES = frozenset({
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
# FPS Booster (CPU + GPU rows)
# ---------------------------------------------------------------------------

FPS_SETTING_KEYS = setting_keys.FPS_KEYS

# Stutter-prevention bundle for CS2.  `disable_hags` requires a reboot to
# take effect, so applying it mid-session does nothing useful and would only
# add risk on the Restore path.  `visual_effects_off` is intentionally
# excluded — it changes desktop animation globally, too invasive for an auto
# plan.
#
# `pcores_affinity` is intentionally excluded: pinning CS2 to P-cores only
# starves the E-core threads Source 2 uses for audio, networking, and shader
# compilation, and the post-apply re-pin window (MainWindow) forces repeated
# thread migrations — both produce micro-stutter (see core/settings_risk.py).
# It stays available as a manual FPS toggle for users who want to pin manually.
#
# Both NVIDIA keys are excluded, so this bundle is pure CPU/Windows tweaks and
# performs no NVIDIA registry writes on the apply or restore path:
#   * `nvidia_max_perf` locks the RTX 4060 *Laptop* at its P0 max-clock state,
#     which thermal-throttles after ~10 min; the resulting clock oscillation
#     shows up as frame-time variance / stutter.
#   * `nvidia_ull` (driver Ultra-Low-Latency / render-ahead trim) is redundant
#     for CS2 — the game ships native NVIDIA Reflex, which supersedes the
#     driver knob and paces the render queue better; at CS2's CPU-bound high
#     frame rates the driver setting is effectively a no-op.
# Both stay available as manual FPS toggles.  With no NVIDIA keys active, CS2
# Game Mode also skips the nvidia-smi GPU-temp poller (MainWindow gates it on
# `nvidia_max_perf`/`nvidia_ull`).
CS2_FPS_ENABLED_KEYS = frozenset({
    "power_plan",
    "timer_resolution",
    "game_dvr_off",
    "fullscreen_opt_off",
    "sysmain_off",
})

# ---------------------------------------------------------------------------
# Optimizer (Background Killer rows only — TCP/DNS deliberately excluded)
# ---------------------------------------------------------------------------

# System Tweaks (force_msi_mode / disable_ndu / disable_network_throttling) are
# part of OPTIMIZER_KEYS but require reboot, so they stay opt-in — deliberately
# excluded from CS2_OPTIMIZER_ENABLED_KEYS until the user has reboot-validated
# them once. Adding them to the auto bundle for CS2 is a future-PR step.
OPTIMIZER_SETTING_KEYS = setting_keys.OPTIMIZER_KEYS

# Background-bandwidth bundle for CS2.  `pause_telemetry` catches DiagTrack,
# the most common silent ping-spike source on a clean Win11 install.  TCP
# tweaks are excluded because CS2 is UDP — they would do nothing for the
# live game traffic and only clutter the applied-badges UI.
CS2_OPTIMIZER_ENABLED_KEYS = frozenset({
    "pause_windows_update",
    "pause_onedrive",
    "pause_bits",
    "pause_telemetry",
})


# ---------------------------------------------------------------------------
# Predicates and dict-shape helpers
# ---------------------------------------------------------------------------

def is_stable_ping_game(exe_name: str | None) -> bool:
    """Return True when *exe_name* should use the stable-ping policy."""
    if not exe_name:
        return False
    return exe_name.lower() in STABLE_PING_GAME_EXES


def is_dscp_game(exe_name: str | None) -> bool:
    """Return True when *exe_name* should receive an auto DSCP policy."""
    if not exe_name:
        return False
    return exe_name.lower() in DSCP_GAME_EXES


def stable_ping_wifi_settings() -> dict[str, bool]:
    """Return the conservative Wi-Fi settings used by Valorant Stable Ping."""
    return {key: key in VALORANT_WIFI_ENABLED_KEYS for key in WIFI_SETTING_KEYS}


def cs2_wifi_settings() -> dict[str, bool]:
    """Return the CS2 Wi-Fi bundle (Valorant subset + MIMO / BSS-scan keys)."""
    return {key: key in CS2_WIFI_ENABLED_KEYS for key in WIFI_SETTING_KEYS}


def cs2_fps_settings() -> dict[str, bool]:
    """Return the CS2 FPS Booster bundle (CPU/Windows tweaks only)."""
    return {key: key in CS2_FPS_ENABLED_KEYS for key in FPS_SETTING_KEYS}


def cs2_optimizer_settings() -> dict[str, bool]:
    """Return the CS2 Optimizer bundle (Background Killer rows only)."""
    return {key: key in CS2_OPTIMIZER_ENABLED_KEYS for key in OPTIMIZER_SETTING_KEYS}


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

    Stable-ping games get a curated per-game bundle.  When no game is
    running, Game Mode stays armed and applies nothing.  Other detected
    games keep the legacy configured-tab behavior for compatibility.
    """
    if is_stable_ping_game(exe_name):
        lowered = exe_name.lower()
        if lowered == "cs2.exe":
            return {
                "wifi":      cs2_wifi_settings(),
                "fps":       cs2_fps_settings(),
                "optimizer": cs2_optimizer_settings(),
                "dscp":      {"dscp_value": 46},
            }
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
