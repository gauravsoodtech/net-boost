"""
Tests for the VALORANT stable-ping Game Mode policy.
"""

from core.stable_ping_policy import (
    build_game_mode_plan,
    is_stable_ping_game,
    stable_ping_wifi_settings,
)


def test_valorant_detection_is_case_insensitive():
    assert is_stable_ping_game("VALORANT-Win64-Shipping.exe") is True
    assert is_stable_ping_game("valorant-win64-shipping.exe") is True
    assert is_stable_ping_game("cs2.exe") is False
    assert is_stable_ping_game(None) is False


def test_stable_ping_wifi_settings_enable_only_latency_safe_keys():
    settings = stable_ping_wifi_settings()

    enabled = {key for key, value in settings.items() if value is True}

    assert enabled == {
        "disable_lso",
        "disable_interrupt_mod",
        "disable_power_saving",
        "max_tx_power",
    }
    assert settings["minimize_roaming"] is False
    assert settings["prefer_6ghz"] is False
    assert settings["throughput_booster"] is False
    assert settings["disable_bss_scan"] is False
    assert settings["disable_mimo_power_save"] is False


def test_valorant_game_mode_plan_excludes_tcp_dns_services_and_fps():
    plan = build_game_mode_plan(
        "VALORANT-Win64-Shipping.exe",
        current_wifi={"minimize_roaming": True, "throughput_booster": True},
        current_fps={"nvidia_max_perf": True, "power_plan": True},
        current_optimizer={
            "tcp_no_delay": True,
            "tcp_ack_freq": True,
            "tcp_window_scale": True,
            "switch_dns": True,
            "pause_onedrive": True,
        },
    )

    assert set(plan) == {"wifi"}
    assert plan["wifi"] == stable_ping_wifi_settings()


def test_game_mode_plan_is_empty_when_no_game_is_running():
    plan = build_game_mode_plan(
        None,
        current_wifi={"disable_lso": True},
        current_fps={"power_plan": True},
        current_optimizer={"tcp_no_delay": True},
    )

    assert plan == {}
