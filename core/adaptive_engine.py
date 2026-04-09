"""
adaptive_engine.py -- Real-time adaptive network optimization for NetBoost V2.

Monitors ping/jitter/loss readings and automatically adjusts settings when
network conditions degrade.  Each rule evaluates a sliding window of
readings, fires an action when its threshold is breached, and auto-reverts
when conditions stabilise.

Thread-safety: ``on_reading`` is called from the PingMonitor signal on the
main thread (Qt signal delivery).  Rule evaluation is synchronous — keep
rules lightweight.
"""

import logging
import time
from collections import deque
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Reading data-class
# ---------------------------------------------------------------------------

class PingReading:
    __slots__ = ("timestamp", "latency_ms", "timed_out")

    def __init__(self, latency_ms: float, timed_out: bool):
        self.timestamp = time.monotonic()
        self.latency_ms = latency_ms
        self.timed_out = timed_out


# ---------------------------------------------------------------------------
# Abstract rule
# ---------------------------------------------------------------------------

class AdaptiveRule:
    """
    Base class for adaptive optimisation rules.

    Subclasses must implement:
    - ``should_activate(buffer)``  — return True when the rule should fire
    - ``should_deactivate(buffer)`` — return True when conditions recovered
    - ``activate()``  — apply the corrective action
    - ``deactivate()`` — revert the corrective action
    """

    def __init__(self, name: str, cooldown_s: float = 60.0, recovery_s: float = 120.0):
        self.name = name
        self.cooldown_s = cooldown_s
        self.recovery_s = recovery_s
        self.active = False
        self._last_fired: float = 0.0
        self._recovery_start: float | None = None
        self._backup: Any = None

    def evaluate(self, buffer: deque[PingReading]) -> str | None:
        """
        Evaluate the rule against the current buffer.

        Returns a human-readable message if the rule triggered an action,
        or None if no action was taken.
        """
        now = time.monotonic()

        if self.active:
            if self.should_deactivate(buffer):
                if self._recovery_start is None:
                    self._recovery_start = now
                elif now - self._recovery_start >= self.recovery_s:
                    self._do_deactivate()
                    return f"[Auto] {self.name}: conditions recovered — reverted"
            else:
                self._recovery_start = None
            return None

        # Not active — check if we should fire.
        if now - self._last_fired < self.cooldown_s:
            return None

        if self.should_activate(buffer):
            self._do_activate()
            return f"[Auto] {self.name}: activated"

        return None

    def _do_activate(self):
        try:
            self._backup = self.activate()
            self.active = True
            self._last_fired = time.monotonic()
            self._recovery_start = None
            logger.info("Adaptive rule '%s' activated.", self.name)
        except Exception as exc:
            logger.error("Adaptive rule '%s' activation failed: %s", self.name, exc)

    def _do_deactivate(self):
        try:
            self.deactivate(self._backup)
            self.active = False
            self._backup = None
            self._recovery_start = None
            logger.info("Adaptive rule '%s' deactivated (conditions recovered).", self.name)
        except Exception as exc:
            logger.error("Adaptive rule '%s' deactivation failed: %s", self.name, exc)

    # -- subclass hooks --
    def should_activate(self, buffer: deque[PingReading]) -> bool:
        raise NotImplementedError

    def should_deactivate(self, buffer: deque[PingReading]) -> bool:
        raise NotImplementedError

    def activate(self) -> Any:
        raise NotImplementedError

    def deactivate(self, backup: Any) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Concrete rules
# ---------------------------------------------------------------------------

class DnsFailoverRule(AdaptiveRule):
    """
    Cycle to the next DNS provider when packet loss exceeds threshold
    for a sustained period.
    """

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
        self._original_backup: dict | None = None

    def should_activate(self, buffer: deque[PingReading]) -> bool:
        return self._window_loss(buffer) > self._loss_threshold

    def should_deactivate(self, buffer: deque[PingReading]) -> bool:
        return self._window_loss(buffer) < self._loss_threshold / 2

    def activate(self) -> dict:
        dns = self._dns_factory()
        adapter = dns.get_active_adapter()
        backup = {"adapter": adapter, "original_dns": dns.get_current_dns(adapter)}

        # Cycle to next provider.
        self._current_index = (self._current_index + 1) % len(self.PROVIDERS_CYCLE)
        provider = self.PROVIDERS_CYCLE[self._current_index]
        dns.apply(provider, adapter=adapter)
        logger.info("DNS failover: switched to '%s'.", provider)
        return backup

    def deactivate(self, backup: dict) -> None:
        if backup:
            dns = self._dns_factory()
            dns.restore(backup)
            logger.info("DNS failover: restored original DNS.")

    def _window_loss(self, buffer: deque[PingReading]) -> float:
        now = time.monotonic()
        recent = [r for r in buffer if now - r.timestamp <= self._window_s]
        if len(recent) < 5:
            return 0.0
        timeouts = sum(1 for r in recent if r.timed_out)
        return (timeouts / len(recent)) * 100.0


class PingSpikeRule(AdaptiveRule):
    """
    Enable LSO disable (the most impactful Wi-Fi tweak) when repeated
    ping spikes are detected — even if the user didn't toggle it on.
    """

    def __init__(
        self,
        wifi_optimizer_factory: Callable,
        state_guard=None,
        spike_ms: float = 50.0,
        spike_count: int = 3,
        window_s: float = 60.0,
    ):
        super().__init__("Ping Spike → LSO Disable", cooldown_s=120.0, recovery_s=180.0)
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

    def activate(self) -> dict:
        from core.wifi_optimizer import WifiOptimizer
        wifi = self._wifi_factory()
        backup = wifi.apply({"disable_lso": True, "disable_interrupt_mod": True})
        if self._state_guard:
            self._state_guard.record_wifi_backup(backup)
        logger.info("Ping spike rule: LSO + interrupt moderation disabled.")
        return backup

    def deactivate(self, backup: dict) -> None:
        if backup:
            from core.wifi_optimizer import WifiOptimizer
            wifi = self._wifi_factory()
            wifi.restore(backup)
            logger.info("Ping spike rule: LSO settings reverted.")


class BackgroundEscalationRule(AdaptiveRule):
    """
    Pause additional background services when packet loss spikes during gaming.
    """

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

    def activate(self) -> dict:
        bk = self._bg_factory()
        settings = {
            "pause_windows_update": True,
            "pause_bits": True,
            "pause_telemetry": True,
        }
        backup = bk.apply(settings)
        if self._state_guard:
            for svc in backup.get("services_backup", []):
                self._state_guard.add_paused_service(svc["name"])
        logger.info("Background escalation: paused additional services.")
        return backup

    def deactivate(self, backup: dict) -> None:
        if backup:
            from core.background_killer import resume_service, resume_process
            for svc in backup.get("services_backup", []):
                try:
                    resume_service(svc["name"])
                except Exception:
                    pass
            for pid in backup.get("suspended_pids", []):
                try:
                    resume_process(pid)
                except Exception:
                    pass
            logger.info("Background escalation: services resumed.")


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AdaptiveEngine:
    """
    Coordinates adaptive rules based on PingMonitor readings.

    Usage::

        engine = AdaptiveEngine()
        engine.add_rule(DnsFailoverRule(...))
        engine.add_rule(PingSpikeRule(...))
        # Call from PingMonitor signal:
        engine.on_reading(host, latency_ms, timed_out)
    """

    def __init__(self, buffer_size: int = 240):
        self._buffer: deque[PingReading] = deque(maxlen=buffer_size)
        self._rules: list[AdaptiveRule] = []
        self._enabled = False
        self._action_callback: Callable[[str], None] | None = None

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

    def set_action_callback(self, callback: Callable[[str], None]) -> None:
        """Set a callback that receives human-readable action messages."""
        self._action_callback = callback

    def on_reading(self, host: str, latency_ms: float, timed_out: bool) -> None:
        """Called on every ping reading. Evaluates all rules."""
        self._buffer.append(PingReading(latency_ms, timed_out))

        if not self._enabled:
            return

        for rule in self._rules:
            try:
                msg = rule.evaluate(self._buffer)
                if msg and self._action_callback:
                    self._action_callback(msg)
            except Exception as exc:
                logger.error("Adaptive rule '%s' error: %s", rule.name, exc)

    def deactivate_all(self) -> None:
        """Revert all active rules."""
        for rule in self._rules:
            if rule.active:
                rule._do_deactivate()

    def get_active_rules(self) -> list[str]:
        """Return names of currently active rules."""
        return [r.name for r in self._rules if r.active]
