"""
Tests for the CS2 stable-ping policy.

CS2 uses the same monitoring-only Game Mode surface as Valorant:

- Wi-Fi registry tweaks stay manual troubleshooting toggles.
- FPS Booster, Optimizer (background killer / TCP / DNS), and per-app DSCP QoS
  are not in the CS2 auto plan.

Valorant and CS2 must not regress into automatic Wi-Fi writes.
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


def test_cs2_wifi_bundle_matches_monitoring_only_valorant_keys():
    assert CS2_WIFI_ENABLED_KEYS == VALORANT_WIFI_ENABLED_KEYS
    assert CS2_WIFI_ENABLED_KEYS == frozenset()
    assert "disable_mimo_power_save" not in CS2_WIFI_ENABLED_KEYS
    assert "disable_bss_scan" not in CS2_WIFI_ENABLED_KEYS
    assert "throughput_booster" not in CS2_WIFI_ENABLED_KEYS


def test_cs2_wifi_settings_helper_shape():
    settings = cs2_wifi_settings()

    assert {key for key, value in settings.items() if value} == CS2_WIFI_ENABLED_KEYS
    assert settings["disable_lso"] is False
    assert settings["disable_interrupt_mod"] is False
    assert settings["disable_power_saving"] is False
    assert settings["max_tx_power"] is False
    assert settings["disable_mimo_power_save"] is False
    assert settings["disable_bss_scan"] is False
    assert settings["throughput_booster"] is False
    assert settings["prefer_6ghz"] is False


def test_cs2_game_mode_plan_is_monitoring_only():
    """CS2 never auto-applies Wi-Fi / FPS / Optimizer / DSCP sections."""
    plan = build_game_mode_plan(
        "cs2.exe",
        current_wifi={"throughput_booster": False},   # ignored; auto plan wins
        current_fps={"nvidia_max_perf": True},         # must not leak into the plan
        current_optimizer={"tcp_no_delay": True},      # must not leak into the plan
    )

    assert plan == {}


def test_cs2_plan_is_case_insensitive_on_exe_name():
    plan = build_game_mode_plan("CS2.EXE")
    assert plan == {}


def test_valorant_plan_stays_monitoring_only():
    plan = build_game_mode_plan(
        "VALORANT-Win64-Shipping.exe",
        current_wifi={"throughput_booster": True},
        current_fps={"nvidia_max_perf": True},
        current_optimizer={"tcp_no_delay": True},
    )

    assert plan == {}


def test_non_stable_ping_game_keeps_legacy_passthrough():
    """Unknown games still use the currently configured tab values."""
    plan = build_game_mode_plan(
        "someothergame.exe",
        current_wifi={"disable_lso": True},
        current_fps={"power_plan": True},
        current_optimizer={"pause_telemetry": True},
    )
    assert plan == {
        "wifi": {"disable_lso": True},
        "fps": {"power_plan": True},
        "optimizer": {"pause_telemetry": True},
    }


def test_no_game_returns_empty_plan():
    assert build_game_mode_plan(None) == {}
    assert build_game_mode_plan("") == {}
