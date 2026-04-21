"""
tests/test_settings_risk.py
Unit tests for core/settings_risk.py — no admin, no hardware required.
"""

import pytest
from core.settings_risk import (
    RISK_REGISTRY,
    get_risk,
    filter_by_level,
    _LEVEL_ORDER,
)


class TestGetRisk:
    def test_known_key_returns_entry(self):
        entry = get_risk("minimize_roaming")
        assert entry is not None
        assert entry["level"] == "HIGH"
        assert entry["tab"] == "wifi"

    def test_unknown_key_returns_none(self):
        assert get_risk("nonexistent_key_xyz") is None

    def test_all_entries_have_required_fields(self):
        required = {"level", "tab", "display", "cause", "advice"}
        for key, entry in RISK_REGISTRY.items():
            missing = required - entry.keys()
            assert not missing, f"Key '{key}' missing fields: {missing}"

    def test_all_levels_are_valid(self):
        valid = {"HIGH", "MEDIUM", "LOW"}
        for key, entry in RISK_REGISTRY.items():
            assert entry["level"] in valid, f"Key '{key}' has invalid level '{entry['level']}'"

    def test_all_tabs_are_valid(self):
        valid = {"wifi", "fps", "optimizer"}
        for key, entry in RISK_REGISTRY.items():
            assert entry["tab"] in valid, f"Key '{key}' has invalid tab '{entry['tab']}'"


class TestFilterByLevel:
    def test_high_before_medium(self):
        keys = ["nvidia_max_perf", "minimize_roaming", "pause_onedrive"]
        results = filter_by_level(keys, min_level="MEDIUM")
        levels = [entry["level"] for _, entry in results]
        # HIGH entries must come before MEDIUM entries
        high_indices = [i for i, l in enumerate(levels) if l == "HIGH"]
        medium_indices = [i for i, l in enumerate(levels) if l == "MEDIUM"]
        if high_indices and medium_indices:
            assert max(high_indices) < min(medium_indices)

    def test_low_excluded_when_min_medium(self):
        keys = ["power_plan", "timer_resolution", "minimize_roaming"]
        results = filter_by_level(keys, min_level="MEDIUM")
        result_keys = [k for k, _ in results]
        assert "power_plan" not in result_keys
        assert "timer_resolution" not in result_keys
        assert "minimize_roaming" in result_keys

    def test_low_included_when_min_low(self):
        keys = ["power_plan", "minimize_roaming"]
        results = filter_by_level(keys, min_level="LOW")
        result_keys = [k for k, _ in results]
        assert "power_plan" in result_keys
        assert "minimize_roaming" in result_keys

    def test_unknown_keys_ignored(self):
        keys = ["minimize_roaming", "totally_unknown_key"]
        results = filter_by_level(keys, min_level="MEDIUM")
        result_keys = [k for k, _ in results]
        assert "minimize_roaming" in result_keys
        assert "totally_unknown_key" not in result_keys

    def test_empty_input_returns_empty(self):
        assert filter_by_level([], min_level="MEDIUM") == []

    def test_all_low_returns_empty_for_medium_threshold(self):
        keys = ["power_plan", "timer_resolution", "game_dvr_off"]
        results = filter_by_level(keys, min_level="MEDIUM")
        assert results == []

    def test_nvidia_max_perf_is_medium(self):
        results = filter_by_level(["nvidia_max_perf"], min_level="MEDIUM")
        assert len(results) == 1
        assert results[0][0] == "nvidia_max_perf"
        assert results[0][1]["level"] == "MEDIUM"

    def test_tcp_tweaks_are_medium_for_stable_ping_mode(self):
        results = filter_by_level(["tcp_no_delay", "tcp_ack_freq"], min_level="MEDIUM")
        result_keys = [key for key, _ in results]
        assert result_keys == ["tcp_no_delay", "tcp_ack_freq"]

    def test_sort_order_stability(self):
        """Multiple HIGH keys should all precede any MEDIUM keys."""
        keys = ["minimize_roaming", "pause_onedrive", "nvidia_max_perf", "disable_hags"]
        results = filter_by_level(keys, min_level="MEDIUM")
        high_done = False
        for _, entry in results:
            if entry["level"] == "HIGH":
                assert not high_done, "HIGH entry appeared after MEDIUM entry"
            if entry["level"] == "MEDIUM":
                high_done = True
