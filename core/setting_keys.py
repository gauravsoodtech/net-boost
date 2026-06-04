"""
core/setting_keys.py — canonical registry of NetBoost UI toggle keys.

Single source of truth for every optimizer toggle key name.  These exact
strings are a contract shared across five layers:

  * the UI toggle rows — ``ui/tab_wifi.py``, ``ui/tab_fps.py``,
    ``ui/tab_optimizer.py`` each populate ``_toggle_rows[key]``,
  * the risk registry — ``core/settings_risk.py``,
  * the stable-ping Game Mode policy — ``core/stable_ping_policy.py``,
  * the profile JSON schema — ``core/profile_manager.py``, and
  * every backend ``apply(settings)`` that reads ``settings.get(key)``.

A typo or omission in any one layer silently no-ops the toggle: the apply
branch never fires, or the profile never persists the value, with no error.
This module makes the key set declarative, and ``tests/test_setting_keys.py``
asserts every layer agrees with it — turning a silent no-op into a loud test
failure.

Pure Python, zero project imports — safe for any module (Qt or not) to import.
"""

from __future__ import annotations

# --------------------------------------------------------------------- Wi-Fi
# Routes to core/wifi_optimizer.py.  Order mirrors the Wi-Fi tab toggle rows.
WIFI_KEYS: tuple[str, ...] = (
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

# ----------------------------------------------------------------- FPS Booster
# CPU/Windows rows route to core/fps_booster.py; GPU rows route to
# core/nvidia_optimizer.py via the nvidia_max_perf -> max_power and
# nvidia_ull -> ull_mode key translation in MainWindow._apply_fps.
FPS_CPU_KEYS: tuple[str, ...] = (
    "power_plan",
    "pcores_affinity",
    "timer_resolution",
    "game_dvr_off",
    "fullscreen_opt_off",
    "sysmain_off",
    "visual_effects_off",
)
FPS_GPU_KEYS: tuple[str, ...] = (
    "nvidia_max_perf",
    "nvidia_ull",
    "disable_hags",
)
FPS_KEYS: tuple[str, ...] = FPS_CPU_KEYS + FPS_GPU_KEYS

# ------------------------------------------------------------------- Optimizer
# The Optimizer tab fans out to four backends; each sub-group maps to its own
# profile JSON section (see PROFILE_SECTION_KEYS).
TCP_KEYS: tuple[str, ...] = (
    "tcp_no_delay",
    "tcp_ack_freq",
    "tcp_window_scale",
)
DNS_KEYS: tuple[str, ...] = (
    "switch_dns",
)
BACKGROUND_KILLER_KEYS: tuple[str, ...] = (
    "pause_windows_update",
    "pause_onedrive",
    "pause_bits",
    "pause_telemetry",
)
SYSTEM_TWEAK_KEYS: tuple[str, ...] = (
    "force_msi_mode",
    "disable_ndu",
    "disable_network_throttling",
)
OPTIMIZER_KEYS: tuple[str, ...] = (
    TCP_KEYS + DNS_KEYS + BACKGROUND_KILLER_KEYS + SYSTEM_TWEAK_KEYS
)

# ----------------------------------------------------------------------- Unions
ALL_KEYS: frozenset[str] = frozenset(WIFI_KEYS + FPS_KEYS + OPTIMIZER_KEYS)

# Tab ownership — must match the ``tab`` field in core/settings_risk.py.
TAB_BY_KEY: dict[str, str] = {
    **{k: "wifi" for k in WIFI_KEYS},
    **{k: "fps" for k in FPS_KEYS},
    **{k: "optimizer" for k in OPTIMIZER_KEYS},
}

# Profile JSON section -> the toggle keys that section must serialize.
# Sections also carry non-toggle fields (e.g. dns_provider, enabled) which are
# intentionally NOT part of the canonical toggle-key set.  The ``bandwidth``
# and ``nvidia_optimizer`` profile sections are likewise excluded: their keys
# (game_priority, ull_mode/max_power/dynamic_pstate_off) are not UI toggle keys
# routed through the apply gates.
PROFILE_SECTION_KEYS: dict[str, tuple[str, ...]] = {
    "wifi_optimizer": WIFI_KEYS,
    "fps_boost": FPS_KEYS,
    "tcp_optimizer": TCP_KEYS,
    "dns": DNS_KEYS,
    "background_killer": BACKGROUND_KILLER_KEYS,
    "system_tweaks": SYSTEM_TWEAK_KEYS,
}


def tab_for(key: str) -> str | None:
    """Return the owning tab ("wifi" / "fps" / "optimizer") for *key*, or None."""
    return TAB_BY_KEY.get(key)


def is_known_key(key: str) -> bool:
    """Return True when *key* is a canonical optimizer toggle key."""
    return key in ALL_KEYS
