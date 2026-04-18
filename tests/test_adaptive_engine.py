"""
Tests for core/adaptive_engine.py — AdaptiveEngine and concrete rules.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch
from collections import deque

from core.adaptive_engine import (
    AdaptiveEngine,
    AdaptiveRecommendation,
    AdaptiveRule,
    BackgroundEscalationRule,
    DnsFailoverRule,
    PingReading,
    PingSpikeRule,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_readings(latencies, timed_out_flags=None, window_s=0):
    """Build a deque of PingReading objects with timestamps close to now."""
    buf = deque()
    now = time.monotonic()
    n = len(latencies)
    for i, lat in enumerate(latencies):
        to = timed_out_flags[i] if timed_out_flags else False
        r = PingReading(lat, to)
        # Space readings evenly within the window so they're all "recent".
        r.timestamp = now - (window_s * (n - 1 - i) / max(n - 1, 1))
        buf.append(r)
    return buf


class TestAdaptiveEngineCore:

    def test_on_reading_feeds_buffer(self):
        engine = AdaptiveEngine(buffer_size=5)
        for i in range(7):
            engine.on_reading("1.1.1.1", float(i), False)
        # Buffer capped at 5
        assert len(engine._buffer) == 5
        assert engine._buffer[0].latency_ms == 2.0  # oldest kept

    def test_enabled_false_prevents_rule_evaluation(self):
        engine = AdaptiveEngine()
        rule = MagicMock(spec=AdaptiveRule)
        rule.active = False
        engine.add_rule(rule)
        engine.enabled = False

        engine.on_reading("1.1.1.1", 10.0, False)

        rule.evaluate.assert_not_called()

    def test_enabled_true_evaluates_rules(self):
        engine = AdaptiveEngine()
        rule = MagicMock(spec=AdaptiveRule)
        rule.active = False
        rule.evaluate.return_value = None
        engine.add_rule(rule)
        engine.enabled = True

        engine.on_reading("1.1.1.1", 10.0, False)

        rule.evaluate.assert_called_once()

    def test_deactivate_all_clears_active_rules(self):
        engine = AdaptiveEngine()
        rule = MagicMock(spec=AdaptiveRule)
        rule.active = True
        engine.add_rule(rule)

        engine.deactivate_all()

        rule.clear_pending.assert_called_once()

    def test_get_active_rules_returns_correct_names(self):
        engine = AdaptiveEngine()
        r1 = MagicMock(spec=AdaptiveRule)
        r1.name = "Rule A"
        r1.active = True
        r2 = MagicMock(spec=AdaptiveRule)
        r2.name = "Rule B"
        r2.active = False
        engine.add_rule(r1)
        engine.add_rule(r2)

        assert engine.get_active_rules() == ["Rule A"]

    def test_recommendation_callback_receives_recommendation(self):
        engine = AdaptiveEngine()
        callback = MagicMock()
        engine.set_recommendation_callback(callback)

        rule = MagicMock(spec=AdaptiveRule)
        rule.active = False
        rule.name = "Test Rule"
        rec = AdaptiveRecommendation(
            id="test-rule:optimizer",
            rule_name="Test Rule",
            severity="MEDIUM",
            title="Test recommendation",
            message="Try this safer fix.",
            target="optimizer",
            settings_patch={"pause_bits": True},
        )
        rule.evaluate.return_value = rec
        engine.add_rule(rule)
        engine.enabled = True

        engine.on_reading("1.1.1.1", 10.0, False)

        callback.assert_called_once_with(rec)

    def test_disabled_engine_clears_pending_recommendations(self):
        engine = AdaptiveEngine()
        callback = MagicMock()
        engine.set_recommendation_callback(callback)
        rec = AdaptiveRecommendation(
            id="test-rule:wifi",
            rule_name="Test Rule",
            severity="HIGH",
            title="Wi-Fi recommendation",
            message="Disable packet batching.",
            target="wifi",
            settings_patch={"disable_lso": True},
        )
        rule = MagicMock(spec=AdaptiveRule)
        rule.active = False
        rule.name = "Test Rule"
        rule.evaluate.return_value = rec
        engine.add_rule(rule)

        engine.enabled = True
        engine.on_reading("1.1.1.1", 80.0, False)
        engine.enabled = False
        engine.enabled = True
        engine.on_reading("1.1.1.1", 85.0, False)

        assert callback.call_count == 2


class TestDnsFailoverRule:

    def _make_rule(self):
        dns_mock = MagicMock()
        dns_mock.get_active_adapter.return_value = "Wi-Fi"
        dns_mock.get_current_dns.return_value = "1.1.1.1"
        dns_mock.apply.return_value = None
        factory = MagicMock(return_value=dns_mock)
        rule = DnsFailoverRule(factory, loss_threshold=10.0, window_s=30.0)
        return rule, factory, dns_mock

    def test_activates_when_loss_above_threshold(self):
        rule, factory, dns_mock = self._make_rule()
        # 6 out of 10 readings timed out → 60% loss > 10% threshold
        timeouts = [True] * 6 + [False] * 4
        buf = _make_readings([0.0] * 10, timeouts, window_s=10)

        assert rule.should_activate(buf) is True

    def test_does_not_activate_during_cooldown(self):
        rule, factory, dns_mock = self._make_rule()
        timeouts = [True] * 6 + [False] * 4
        buf = _make_readings([0.0] * 10, timeouts, window_s=10)

        # First activation
        rule._do_activate()
        assert rule.active is True

        # Manually deactivate and try again — cooldown blocks
        rule.active = False
        result = rule.evaluate(buf)
        assert result is None  # blocked by cooldown

    def test_does_not_activate_with_low_loss(self):
        rule, factory, dns_mock = self._make_rule()
        buf = _make_readings([5.0] * 10, [False] * 10, window_s=10)
        assert rule.should_activate(buf) is False

    def test_deactivates_when_loss_recovers(self):
        rule, factory, dns_mock = self._make_rule()
        # Loss below threshold/2 = 5%: 0 out of 10 timed out
        buf = _make_readings([5.0] * 10, [False] * 10, window_s=10)
        assert rule.should_deactivate(buf) is True

    def test_recommendation_does_not_touch_dns_until_user_applies(self):
        rule, factory, dns_mock = self._make_rule()
        timeouts = [True] * 6 + [False] * 4
        buf = _make_readings([0.0] * 10, timeouts, window_s=10)

        rec = rule.evaluate(buf)

        assert isinstance(rec, AdaptiveRecommendation)
        assert rec.target == "optimizer"
        assert rec.settings_patch == {
            "switch_dns": True,
            "dns_provider": "Cloudflare 1.1.1.1",
        }
        factory.assert_not_called()
        dns_mock.apply.assert_not_called()


class TestPingSpikeRule:

    def _make_rule(self):
        wifi_mock = MagicMock()
        wifi_mock.apply.return_value = {"_adapter_found": True}
        factory = MagicMock(return_value=wifi_mock)
        rule = PingSpikeRule(factory, spike_ms=50.0, spike_count=3, window_s=60.0)
        return rule, factory, wifi_mock

    def test_activates_on_enough_spikes(self):
        rule, _, _ = self._make_rule()
        # 4 spikes > 50ms in window
        latencies = [10.0, 60.0, 70.0, 5.0, 80.0, 10.0, 90.0]
        buf = _make_readings(latencies, window_s=30)
        assert rule.should_activate(buf) is True

    def test_does_not_activate_with_few_spikes(self):
        rule, _, _ = self._make_rule()
        latencies = [10.0, 60.0, 5.0, 15.0, 20.0]
        buf = _make_readings(latencies, window_s=30)
        assert rule.should_activate(buf) is False

    def test_deactivates_when_no_spikes(self):
        rule, _, _ = self._make_rule()
        latencies = [5.0] * 15
        buf = _make_readings(latencies, window_s=30)
        assert rule.should_deactivate(buf) is True

    def test_does_not_deactivate_with_too_few_readings(self):
        rule, _, _ = self._make_rule()
        latencies = [5.0] * 5  # < 10 required
        buf = _make_readings(latencies, window_s=30)
        assert rule.should_deactivate(buf) is False

    def test_recommendation_contains_wifi_patch_without_applying(self):
        rule, factory, wifi_mock = self._make_rule()
        latencies = [10.0, 60.0, 70.0, 5.0, 80.0]
        buf = _make_readings(latencies, window_s=30)

        rec = rule.evaluate(buf)

        assert isinstance(rec, AdaptiveRecommendation)
        assert rec.target == "wifi"
        assert rec.settings_patch == {
            "disable_lso": True,
            "disable_interrupt_mod": True,
        }
        factory.assert_not_called()
        wifi_mock.apply.assert_not_called()


class TestBackgroundEscalationRule:

    def _make_rule(self):
        bk_mock = MagicMock()
        bk_mock.apply.return_value = {"services_backup": [{"name": "wuauserv"}], "suspended_pids": []}
        factory = MagicMock(return_value=bk_mock)
        rule = BackgroundEscalationRule(factory, loss_threshold=8.0, window_s=30.0)
        return rule, factory, bk_mock

    def test_activates_on_high_loss(self):
        rule, _, _ = self._make_rule()
        timeouts = [True] * 3 + [False] * 7  # 30% loss > 8%
        buf = _make_readings([0.0] * 10, timeouts, window_s=10)
        assert rule.should_activate(buf) is True

    def test_does_not_activate_with_few_readings(self):
        rule, _, _ = self._make_rule()
        buf = _make_readings([0.0] * 3, [True] * 3, window_s=10)
        assert rule.should_activate(buf) is False

    def test_deactivates_when_loss_drops(self):
        rule, _, _ = self._make_rule()
        # 0 out of 15 timed out → 0% < 2%
        buf = _make_readings([5.0] * 15, [False] * 15, window_s=10)
        assert rule.should_deactivate(buf) is True


    def test_recommendation_contains_service_patch_without_applying(self):
        rule, factory, bk_mock = self._make_rule()
        timeouts = [True] * 3 + [False] * 7
        buf = _make_readings([0.0] * 10, timeouts, window_s=10)

        rec = rule.evaluate(buf)

        assert isinstance(rec, AdaptiveRecommendation)
        assert rec.target == "optimizer"
        assert rec.settings_patch == {
            "pause_windows_update": True,
            "pause_bits": True,
            "pause_telemetry": True,
        }
        factory.assert_not_called()
        bk_mock.apply.assert_not_called()


class TestRuleRecoveryFlow:

    def test_deactivation_requires_sustained_recovery(self):
        """Rule stays active until recovery_s elapses continuously."""
        rule = MagicMock(spec=AdaptiveRule, wraps=AdaptiveRule("Test", cooldown_s=0, recovery_s=5.0))
        # Use a real rule subclass
        class SimpleRule(AdaptiveRule):
            def __init__(self):
                super().__init__("Simple", cooldown_s=0, recovery_s=0.0)
                self._should_act = False
                self._should_deact = False
            def should_activate(self, buf):
                return self._should_act
            def should_deactivate(self, buf):
                return self._should_deact
            def build_recommendation(self):
                return AdaptiveRecommendation(
                    id="simple:test",
                    rule_name=self.name,
                    severity="LOW",
                    title="Simple recommendation",
                    message="Simple message.",
                    target="optimizer",
                    settings_patch={},
                )

        r = SimpleRule()
        buf = deque()

        # Activate
        r._should_act = True
        msg = r.evaluate(buf)
        assert r.active is True
        assert isinstance(msg, AdaptiveRecommendation)

        # Clear pending after recovery_s=0 elapses
        r._should_deact = True
        msg = r.evaluate(buf)
        msg = r.evaluate(buf)
        assert r.active is False
