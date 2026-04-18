"""
adaptive_engine.py -- Recommendation engine for NetBoost Adaptive Advisor.

Monitors ping/jitter/loss readings and recommends targeted fixes when network
conditions degrade. Rules do not directly mutate Windows settings; MainWindow
routes accepted recommendations through the same explicit apply/restore paths
used by the normal UI.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)


_DNS_DISPLAY_NAMES = {
    "opendns": "OpenDNS 208.67.222.222",
    "cloudflare": "Cloudflare 1.1.1.1",
    "google": "Google 8.8.8.8",
    "quad9": "Quad9 9.9.9.9",
}


@dataclass
class AdaptiveRecommendation:
    """A user-approved action suggested by Adaptive Advisor."""

    id: str
    rule_name: str
    severity: str
    title: str
    message: str
    target: str
    settings_patch: dict
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "rule_name": self.rule_name,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "target": self.target,
            "settings_patch": dict(self.settings_patch),
            "created_at": self.created_at,
        }


class PingReading:
    __slots__ = ("timestamp", "latency_ms", "timed_out")

    def __init__(self, latency_ms: float, timed_out: bool):
        self.timestamp = time.monotonic()
        self.latency_ms = latency_ms
        self.timed_out = timed_out


class AdaptiveRule:
    """
    Base class for adaptive recommendation rules.

    ``active`` means a recommendation is currently pending or the triggering
    condition has not recovered. It does not mean a Windows setting was applied.
    """

    def __init__(self, name: str, cooldown_s: float = 60.0, recovery_s: float = 120.0):
        self.name = name
        self.cooldown_s = cooldown_s
        self.recovery_s = recovery_s
        self.active = False
        self._last_fired: float = 0.0
        self._recovery_start: float | None = None
        self._last_recommendation_id: str | None = None

    def evaluate(self, buffer: deque[PingReading]) -> AdaptiveRecommendation | None:
        """Evaluate the rule and return a recommendation when approval is needed."""
        now = time.monotonic()

        if self.active:
            if self.should_deactivate(buffer):
                if self._recovery_start is None:
                    self._recovery_start = now
                elif now - self._recovery_start >= self.recovery_s:
                    self.clear_pending(self._last_recommendation_id)
            else:
                self._recovery_start = None
            return None

        if now - self._last_fired < self.cooldown_s:
            return None

        if self.should_activate(buffer):
            return self._do_activate()

        return None

    def _do_activate(self) -> AdaptiveRecommendation | None:
        try:
            recommendation = self.build_recommendation()
            self.active = True
            self._last_fired = time.monotonic()
            self._recovery_start = None
            self._last_recommendation_id = recommendation.id
            logger.info("Adaptive rule '%s' recommended '%s'.", self.name, recommendation.title)
            return recommendation
        except Exception as exc:
            logger.error("Adaptive rule '%s' recommendation failed: %s", self.name, exc)
            return None

    def clear_pending(self, recommendation_id: str | None = None) -> None:
        if recommendation_id is None or recommendation_id == self._last_recommendation_id:
            self.active = False
            self._recovery_start = None
            self._last_recommendation_id = None

    def should_activate(self, buffer: deque[PingReading]) -> bool:
        raise NotImplementedError

    def should_deactivate(self, buffer: deque[PingReading]) -> bool:
        raise NotImplementedError

    def build_recommendation(self) -> AdaptiveRecommendation:
        raise NotImplementedError


class DnsFailoverRule(AdaptiveRule):
    """Recommend cycling DNS providers when packet loss is sustained."""

    PROVIDERS_CYCLE = ["opendns", "cloudflare", "google", "quad9"]

    def __init__(
        self,
        dns_switcher_factory: Callable,
        state_guard=None,
        loss_threshold: float = 10.0,
        window_s: float = 30.0,
    ):
        super().__init__("DNS Failover", cooldown_s=90.0, recovery_s=120.0)
        self._dns_factory = dns_switcher_factory
        self._state_guard = state_guard
        self._loss_threshold = loss_threshold
        self._window_s = window_s
        self._current_index = 0

    def should_activate(self, buffer: deque[PingReading]) -> bool:
        return self._window_loss(buffer) > self._loss_threshold

    def should_deactivate(self, buffer: deque[PingReading]) -> bool:
        return self._window_loss(buffer) < self._loss_threshold / 2

    def build_recommendation(self) -> AdaptiveRecommendation:
        self._current_index = (self._current_index + 1) % len(self.PROVIDERS_CYCLE)
        provider = self.PROVIDERS_CYCLE[self._current_index]
        display = _DNS_DISPLAY_NAMES[provider]
        return AdaptiveRecommendation(
            id=f"dns-failover:{provider}",
            rule_name=self.name,
            severity="MEDIUM",
            title=f"Switch DNS to {display}",
            message=(
                "Packet loss stayed high. Try switching DNS providers; NetBoost "
                "will apply it through the normal optimizer path if you approve."
            ),
            target="optimizer",
            settings_patch={
                "switch_dns": True,
                "dns_provider": display,
            },
        )

    def _window_loss(self, buffer: deque[PingReading]) -> float:
        now = time.monotonic()
        recent = [r for r in buffer if now - r.timestamp <= self._window_s]
        if len(recent) < 5:
            return 0.0
        timeouts = sum(1 for r in recent if r.timed_out)
        return (timeouts / len(recent)) * 100.0


class PingSpikeRule(AdaptiveRule):
    """Recommend Wi-Fi packet batching changes when repeated spikes occur."""

    def __init__(
        self,
        wifi_optimizer_factory: Callable,
        state_guard=None,
        spike_ms: float = 50.0,
        spike_count: int = 3,
        window_s: float = 60.0,
    ):
        super().__init__("Ping Spike -> LSO Disable", cooldown_s=120.0, recovery_s=180.0)
        self._wifi_factory = wifi_optimizer_factory
        self._state_guard = state_guard
        self._spike_ms = spike_ms
        self._spike_count = spike_count
        self._window_s = window_s

    def should_activate(self, buffer: deque[PingReading]) -> bool:
        now = time.monotonic()
        spikes = sum(
            1 for r in buffer
            if not r.timed_out
            and r.latency_ms >= self._spike_ms
            and now - r.timestamp <= self._window_s
        )
        return spikes >= self._spike_count

    def should_deactivate(self, buffer: deque[PingReading]) -> bool:
        now = time.monotonic()
        recent = [r for r in buffer if now - r.timestamp <= self._window_s and not r.timed_out]
        if len(recent) < 10:
            return False
        spikes = sum(1 for r in recent if r.latency_ms >= self._spike_ms)
        return spikes == 0

    def build_recommendation(self) -> AdaptiveRecommendation:
        return AdaptiveRecommendation(
            id="ping-spike-lso:wifi",
            rule_name=self.name,
            severity="HIGH",
            title="Disable LSO and interrupt moderation",
            message=(
                "Repeated ping spikes were detected. Disabling NIC packet batching "
                "and interrupt moderation is the safest targeted Wi-Fi fix to try."
            ),
            target="wifi",
            settings_patch={
                "disable_lso": True,
                "disable_interrupt_mod": True,
            },
        )


class BackgroundEscalationRule(AdaptiveRule):
    """Recommend pausing background services when packet loss spikes."""

    def __init__(
        self,
        bg_killer_factory: Callable,
        state_guard=None,
        loss_threshold: float = 8.0,
        window_s: float = 30.0,
    ):
        super().__init__("Background Escalation", cooldown_s=120.0, recovery_s=180.0)
        self._bg_factory = bg_killer_factory
        self._state_guard = state_guard
        self._loss_threshold = loss_threshold
        self._window_s = window_s

    def should_activate(self, buffer: deque[PingReading]) -> bool:
        now = time.monotonic()
        recent = [r for r in buffer if now - r.timestamp <= self._window_s]
        if len(recent) < 5:
            return False
        timeouts = sum(1 for r in recent if r.timed_out)
        loss_pct = (timeouts / len(recent)) * 100.0
        return loss_pct > self._loss_threshold

    def should_deactivate(self, buffer: deque[PingReading]) -> bool:
        now = time.monotonic()
        recent = [r for r in buffer if now - r.timestamp <= self._window_s]
        if len(recent) < 10:
            return False
        timeouts = sum(1 for r in recent if r.timed_out)
        return (timeouts / len(recent)) * 100.0 < 2.0

    def build_recommendation(self) -> AdaptiveRecommendation:
        return AdaptiveRecommendation(
            id="background-escalation:optimizer",
            rule_name=self.name,
            severity="MEDIUM",
            title="Pause background network services",
            message=(
                "Packet loss rose while monitoring. Pausing Windows Update, BITS, "
                "and telemetry can reduce background network contention."
            ),
            target="optimizer",
            settings_patch={
                "pause_windows_update": True,
                "pause_bits": True,
                "pause_telemetry": True,
            },
        )


class AdaptiveEngine:
    """Coordinates adaptive recommendation rules based on PingMonitor readings."""

    def __init__(self, buffer_size: int = 240):
        self._buffer: deque[PingReading] = deque(maxlen=buffer_size)
        self._rules: list[AdaptiveRule] = []
        self._enabled = False
        self._recommendation_callback: Callable[[AdaptiveRecommendation], None] | None = None
        self._pending_ids: set[str] = set()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value
        if not value:
            self.deactivate_all()

    def add_rule(self, rule: AdaptiveRule) -> None:
        self._rules.append(rule)

    def set_recommendation_callback(self, callback: Callable[[AdaptiveRecommendation], None]) -> None:
        """Set a callback that receives recommendation objects."""
        self._recommendation_callback = callback

    def set_action_callback(self, callback: Callable[[AdaptiveRecommendation], None]) -> None:
        """Backward-compatible alias for older wiring."""
        self.set_recommendation_callback(callback)

    def on_reading(self, host: str, latency_ms: float, timed_out: bool) -> None:
        """Called on every ping reading. Evaluates all rules."""
        self._buffer.append(PingReading(latency_ms, timed_out))

        if not self._enabled:
            return

        for rule in self._rules:
            try:
                recommendation = rule.evaluate(self._buffer)
                if (
                    recommendation
                    and recommendation.id not in self._pending_ids
                    and self._recommendation_callback
                ):
                    self._pending_ids.add(recommendation.id)
                    self._recommendation_callback(recommendation)
            except Exception as exc:
                logger.error("Adaptive rule '%s' error: %s", rule.name, exc)

    def deactivate_all(self) -> None:
        """Clear all pending recommendations."""
        self._pending_ids.clear()
        for rule in self._rules:
            if rule.active:
                rule.clear_pending()

    def get_active_rules(self) -> list[str]:
        """Return names of currently active rules."""
        return [r.name for r in self._rules if r.active]

    def mark_recommendation_handled(self, recommendation_id: str) -> None:
        """Allow a handled/dismissed recommendation to be emitted again after cooldown."""
        self._pending_ids.discard(recommendation_id)
        for rule in self._rules:
            rule.clear_pending(recommendation_id)
