"""
Stable-ping Game Mode policy.

This module keeps game-session defaults separate from the visible tab state.
The VALORANT policy is deliberately conservative: only targeted Wi-Fi latency
settings are applied automatically, while broad TCP, DNS, service, and FPS
tweaks remain manual.
"""

from __future__ import annotations

STABLE_PING_GAME_EXES = frozenset({
    "valorant-win64-shipping.exe",
})

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

STABLE_PING_WIFI_ENABLED_KEYS = frozenset({
    "disable_lso",
    "disable_interrupt_mod",
    "disable_power_saving",
    "max_tx_power",
})


def is_stable_ping_game(exe_name: str | None) -> bool:
    """Return True when *exe_name* should use the stable-ping policy."""
    if not exe_name:
        return False
    return exe_name.lower() in STABLE_PING_GAME_EXES


def stable_ping_wifi_settings() -> dict[str, bool]:
    """Return the conservative Wi-Fi settings used by Stable Ping Mode."""
    return {
        key: key in STABLE_PING_WIFI_ENABLED_KEYS
        for key in WIFI_SETTING_KEYS
    }


def build_game_mode_plan(
    exe_name: str | None,
    current_wifi: dict | None = None,
    current_fps: dict | None = None,
    current_optimizer: dict | None = None,
) -> dict[str, dict]:
    """
    Build the settings sections Game Mode should apply for *exe_name*.

    VALORANT gets a conservative stable-ping plan. When no game is running,
    Game Mode stays armed and applies nothing. Other detected games keep the
    legacy configured-tab behavior for compatibility.
    """
    if is_stable_ping_game(exe_name):
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
