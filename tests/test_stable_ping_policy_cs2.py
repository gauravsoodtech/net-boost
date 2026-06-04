"""
Tests for the CS2 extension of the stable-ping policy.

CS2 has no kernel anti-cheat (Vanguard), so it can use a slightly wider Wi-Fi
subset than Valorant.  Both games are Wi-Fi-only by design, though:

- CS2 Wi-Fi bundle: Valorant's 4 keys plus ``disable_mimo_power_save`` and
  ``disable_bss_scan`` (suppresses scan-induced periodic spikes).
  ``throughput_booster`` is excluded — its packet bursting causes ping spikes.
- FPS Booster, Optimizer (background killer / TCP / DNS), and per-app DSCP QoS
  are **not** in the CS2 auto plan — they were a recurring source of stutter,
  thermal throttle, and confusion when auto-applied, and stay manual.

Valorant must NOT regress into a wider Wi-Fi surface.
"""

from core.stable_ping_policy import (
    CS2_WIFI_ENABLED_KEYS,
    VALORANT_WIFI_ENABLED_KEYS,
    build_game_mode_plan,
    cs2_wifi_settings,
    is_stable_ping_game,
    stable_ping_wifi_settings,
)


def test_cs2_is_a_stable_ping_game_case_insensitive():
    assert is_stable_ping_game("cs2.exe") is True
    assert is_stable_ping_game("CS2.EXE") is True
    assert is_stable_ping_game("Cs2.Exe") is True


def test_cs2_wifi_bundle_extends_valorant_with_mimo_and_bss_scan_keys():
    assert CS2_WIFI_ENABLED_KEYS >= VALORANT_WIFI_ENABLED_KEYS
    extra = CS2_WIFI_ENABLED_KEYS - VALORANT_WIFI_ENABLED_KEYS
    assert extra == {"disable_mimo_power_save", "disable_bss_scan"}
    # disable_bss_scan suppresses background channel scans → kills periodic
    # scan-induced ping spikes; LOW risk and safe for a stationary CS2 match.
    assert "disable_bss_scan" in CS2_WIFI_ENABLED_KEYS
    # Excluded: packet bursting competes with latency stability → ping spikes.
    assert "throughput_booster" not in CS2_WIFI_ENABLED_KEYS


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


def test_cs2_game_mode_plan_is_wifi_only():
    """CS2 is Wi-Fi-only: FPS / Optimizer / DSCP are never auto-applied, even
    when the corresponding tabs are configured."""
    plan = build_game_mode_plan(
        "cs2.exe",
        current_wifi={"throughput_booster": False},   # ignored — auto plan wins
        current_fps={"nvidia_max_perf": True},         # must NOT leak into the plan
        current_optimizer={"tcp_no_delay": True},      # must NOT leak into the plan
    )

    assert set(plan) == {"wifi"}
    assert plan["wifi"] == cs2_wifi_settings()
    assert "fps" not in plan
    assert "optimizer" not in plan
    assert "dscp" not in plan


def test_cs2_plan_is_case_insensitive_on_exe_name():
    plan = build_game_mode_plan("CS2.EXE")
    assert set(plan) == {"wifi"}
    assert plan["wifi"] == cs2_wifi_settings()


def test_valorant_plan_stays_narrow_and_distinct_from_cs2():
    """Valorant must stay on the conservative 4-key Wi-Fi subset."""
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
    # Valorant does not pick up CS2's extra Wi-Fi keys.
    assert plan["wifi"]["disable_mimo_power_save"] is False
    assert plan["wifi"]["disable_bss_scan"] is False


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
