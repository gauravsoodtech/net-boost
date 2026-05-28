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

WIFI_SETTING_KEYS = (
    "disable_lso",
    "disable_interrupt_mod",
    "disable_power_saving",
    "minimize_roaming",
    "max_tx_power",
    "disable_bss_scan",
    "prefer_6ghz",
    "throughput_booster",
    "disable_mimo_power_save",
)

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

# CS2 — Valorant subset plus the two AX211-friendly throughput keys that
# Valorant deliberately omits.  No Vanguard concerns here.
CS2_WIFI_ENABLED_KEYS = frozenset(VALORANT_WIFI_ENABLED_KEYS | {
    "throughput_booster",
    "disable_mimo_power_save",
})

# ---------------------------------------------------------------------------
# FPS Booster (CPU + GPU rows)
# ---------------------------------------------------------------------------

FPS_SETTING_KEYS = (
    "power_plan",
    "pcores_affinity",
    "timer_resolution",
    "game_dvr_off",
    "fullscreen_opt_off",
    "sysmain_off",
    "visual_effects_off",
    "nvidia_max_perf",
    "nvidia_ull",
    "disable_hags",
)

# Stutter-prevention bundle for CS2.  `disable_hags` requires a reboot to
# take effect, so applying it mid-session does nothing useful and would only
# add risk on the Restore path.  `visual_effects_off` is intentionally
# excluded — it changes desktop animation globally, too invasive for an auto
# plan.
CS2_FPS_ENABLED_KEYS = frozenset({
    "power_plan",
    "pcores_affinity",
    "timer_resolution",
    "game_dvr_off",
    "fullscreen_opt_off",
    "sysmain_off",
    "nvidia_max_perf",
    "nvidia_ull",
})

# ---------------------------------------------------------------------------
# Optimizer (Background Killer rows only — TCP/DNS deliberately excluded)
# ---------------------------------------------------------------------------

OPTIMIZER_SETTING_KEYS = (
    "tcp_no_delay",
    "tcp_ack_freq",
    "tcp_window_scale",
    "switch_dns",
    "pause_windows_update",
    "pause_onedrive",
    "pause_bits",
    "pause_telemetry",
    # System Tweaks (require reboot; opt-in — deliberately excluded from
    # CS2_OPTIMIZER_ENABLED_KEYS until the user has reboot-validated them
    # once. Adding them to the auto bundle for CS2 is a future-PR step.)
    "force_msi_mode",
    "disable_ndu",
    "disable_network_throttling",
)

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
    """Return the CS2 Wi-Fi bundle (Valorant subset + throughput keys)."""
    return {key: key in CS2_WIFI_ENABLED_KEYS for key in WIFI_SETTING_KEYS}


def cs2_fps_settings() -> dict[str, bool]:
    """Return the CS2 FPS Booster bundle (CPU pinning + NVIDIA P0)."""
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
