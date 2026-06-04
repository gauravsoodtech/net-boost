"""
Tests for the CS2 extension of the stable-ping policy.

CS2 has no kernel anti-cheat (Vanguard), so its Game Mode plan is broader
than Valorant's:

- Extended Wi-Fi bundle: Valorant's 4 keys plus ``disable_mimo_power_save``
  and ``disable_bss_scan`` (suppresses scan-induced periodic spikes).
  ``throughput_booster`` is excluded — its packet bursting causes ping spikes.
- FPS Booster bundle (timer/power/DVR — CPU/Windows only).  Both NVIDIA keys
  are excluded: ``nvidia_max_perf`` (RTX 4060 Laptop thermal-throttle →
  stutter) and ``nvidia_ull`` (redundant with CS2's native Reflex).
  ``pcores_affinity`` (starves CS2 E-cores → stutter), ``disable_hags`` and
  ``visual_effects_off`` are excluded too.
- Background Killer bundle (Windows Update, OneDrive, BITS, DiagTrack).
  TCP / DNS deliberately omitted — CS2 is UDP.
- Per-app DSCP EF (46) QoS policy on ``cs2.exe``.

Valorant must NOT regress into any of these expanded paths.
"""

from core.stable_ping_policy import (
    CS2_FPS_ENABLED_KEYS,
    CS2_OPTIMIZER_ENABLED_KEYS,
    CS2_WIFI_ENABLED_KEYS,
    VALORANT_WIFI_ENABLED_KEYS,
    build_game_mode_plan,
    cs2_fps_settings,
    cs2_optimizer_settings,
    cs2_wifi_settings,
    is_dscp_game,
    is_stable_ping_game,
    stable_ping_wifi_settings,
)


def test_cs2_is_a_stable_ping_game_case_insensitive():
    assert is_stable_ping_game("cs2.exe") is True
    assert is_stable_ping_game("CS2.EXE") is True
    assert is_stable_ping_game("Cs2.Exe") is True


def test_cs2_is_a_dscp_game_but_valorant_is_not():
    assert is_dscp_game("cs2.exe") is True
    assert is_dscp_game("CS2.exe") is True
    assert is_dscp_game("VALORANT-Win64-Shipping.exe") is False
    assert is_dscp_game(None) is False
    assert is_dscp_game("") is False


def test_cs2_wifi_bundle_extends_valorant_with_mimo_and_bss_scan_keys():
    assert CS2_WIFI_ENABLED_KEYS >= VALORANT_WIFI_ENABLED_KEYS
    extra = CS2_WIFI_ENABLED_KEYS - VALORANT_WIFI_ENABLED_KEYS
    assert extra == {"disable_mimo_power_save", "disable_bss_scan"}
    # disable_bss_scan suppresses background channel scans → kills periodic
    # scan-induced ping spikes; LOW risk and safe for a stationary CS2 match.
    assert "disable_bss_scan" in CS2_WIFI_ENABLED_KEYS
    # Excluded: packet bursting competes with latency stability → ping spikes.
    assert "throughput_booster" not in CS2_WIFI_ENABLED_KEYS


def test_cs2_fps_bundle_includes_stutter_keys_but_not_reboot_required_keys():
    # Stutter-prevention musts:
    assert {"timer_resolution", "power_plan"} <= CS2_FPS_ENABLED_KEYS
    # Deliberately excluded (pure CPU/Windows bundle — no NVIDIA keys):
    assert "nvidia_ull" not in CS2_FPS_ENABLED_KEYS          # redundant with CS2's native Reflex
    assert "pcores_affinity" not in CS2_FPS_ENABLED_KEYS      # starves CS2 E-cores → stutter
    assert "nvidia_max_perf" not in CS2_FPS_ENABLED_KEYS      # RTX 4060 Laptop thermal-throttle → stutter
    assert "disable_hags" not in CS2_FPS_ENABLED_KEYS         # needs reboot
    assert "visual_effects_off" not in CS2_FPS_ENABLED_KEYS   # too invasive


def test_cs2_optimizer_bundle_is_background_killer_only_no_tcp():
    assert CS2_OPTIMIZER_ENABLED_KEYS == {
        "pause_windows_update",
        "pause_onedrive",
        "pause_bits",
        "pause_telemetry",
    }


def test_cs2_wifi_settings_helper_shape():
    s = cs2_wifi_settings()
    # Six True keys (Valorant's 4 + disable_mimo_power_save + disable_bss_scan),
    # rest False.
    assert {k for k, v in s.items() if v} == CS2_WIFI_ENABLED_KEYS
    assert s["disable_lso"] is True
    assert s["throughput_booster"] is False  # excluded — ping-spike source
    assert s["disable_mimo_power_save"] is True
    assert s["disable_bss_scan"] is True  # suppresses scan-induced periodic spikes
    assert s["prefer_6ghz"] is False  # not in the auto bundle


def test_cs2_fps_settings_helper_shape():
    s = cs2_fps_settings()
    assert s["pcores_affinity"] is False  # excluded — starves CS2 E-cores → stutter
    assert s["timer_resolution"] is True
    assert s["power_plan"] is True
    assert s["nvidia_max_perf"] is False  # excluded — RTX 4060 Laptop thermal-throttle → stutter
    assert s["nvidia_ull"] is False  # excluded — redundant with CS2's native Reflex
    assert s["disable_hags"] is False
    assert s["visual_effects_off"] is False


def test_cs2_optimizer_settings_helper_shape():
    s = cs2_optimizer_settings()
    assert s["pause_windows_update"] is True
    assert s["pause_onedrive"] is True
    assert s["pause_bits"] is True
    assert s["pause_telemetry"] is True
    # TCP / DNS deliberately excluded so _apply_optimizer's branches don't fire.
    assert s["tcp_no_delay"] is False
    assert s["tcp_ack_freq"] is False
    assert s["tcp_window_scale"] is False
    assert s["switch_dns"] is False


def test_cs2_game_mode_plan_includes_all_four_sections():
    plan = build_game_mode_plan(
        "cs2.exe",
        current_wifi={"throughput_booster": False},  # ignored — auto plan wins
        current_fps={"nvidia_max_perf": False},
        current_optimizer={"tcp_no_delay": True},
    )

    assert set(plan) == {"wifi", "fps", "optimizer", "dscp"}
    assert plan["wifi"] == cs2_wifi_settings()
    assert plan["fps"] == cs2_fps_settings()
    assert plan["optimizer"] == cs2_optimizer_settings()
    assert plan["dscp"] == {"dscp_value": 46}


def test_cs2_plan_is_case_insensitive_on_exe_name():
    plan = build_game_mode_plan("CS2.EXE")
    assert set(plan) == {"wifi", "fps", "optimizer", "dscp"}


def test_valorant_plan_does_not_regress_into_cs2_path():
    """The whole point of the per-game split — Valorant must stay narrow."""
    plan = build_game_mode_plan(
        "VALORANT-Win64-Shipping.exe",
        current_wifi={"throughput_booster": True},
        current_fps={"nvidia_max_perf": True},
        current_optimizer={"tcp_no_delay": True},
    )

    assert set(plan) == {"wifi"}
    assert plan["wifi"] == stable_ping_wifi_settings()
    # Vanguard-safe: none of the wider levers.
    assert "fps" not in plan
    assert "optimizer" not in plan
    assert "dscp" not in plan


def test_non_stable_ping_game_keeps_legacy_passthrough():
    """Unknown games still use the currently-configured tab values."""
    plan = build_game_mode_plan(
        "someothergame.exe",
        current_wifi={"disable_lso": True},
        current_fps={"power_plan": True},
        current_optimizer={"pause_telemetry": True},
    )
    assert plan == {
        "wifi":      {"disable_lso": True},
        "fps":       {"power_plan": True},
        "optimizer": {"pause_telemetry": True},
    }


def test_no_game_returns_empty_plan():
    assert build_game_mode_plan(None) == {}
    assert build_game_mode_plan("") == {}
