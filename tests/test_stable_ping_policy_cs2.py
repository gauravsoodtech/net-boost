"""
Tests for the CS2 extension of the stable-ping policy.

CS2 reuses Valorant's conservative 4-key Wi-Fi subset *and* additionally
receives a DSCP intent in the Game Mode plan.  Valorant must not regress
into the DSCP path.
"""

from core.stable_ping_policy import (
    build_game_mode_plan,
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


def test_cs2_game_mode_plan_includes_wifi_and_dscp():
    plan = build_game_mode_plan(
        "cs2.exe",
        current_wifi={"throughput_booster": True},
        current_fps={"nvidia_max_perf": True},
        current_optimizer={"tcp_no_delay": True},
    )

    assert set(plan) == {"wifi", "dscp"}
    assert plan["wifi"] == stable_ping_wifi_settings()
    assert plan["dscp"] == {"dscp_value": 46}


def test_valorant_plan_still_excludes_dscp():
    plan = build_game_mode_plan(
        "VALORANT-Win64-Shipping.exe",
        current_wifi={"throughput_booster": True},
        current_fps={"nvidia_max_perf": True},
        current_optimizer={"tcp_no_delay": True},
    )

    assert set(plan) == {"wifi"}
    assert "dscp" not in plan
