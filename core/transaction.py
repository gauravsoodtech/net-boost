"""
transaction.py -- Transactional apply engine for NetBoost.

Wraps multiple apply steps in an all-or-nothing operation: if any step
fails, all previously completed steps are rolled back automatically.
"""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ApplyTransaction:
    """
    Groups multiple apply/rollback step pairs and executes them atomically.

    Usage::

        tx = ApplyTransaction()
        tx.add_step("TCP",
                     lambda: network_optimizer.apply(settings),
                     lambda backup: network_optimizer.restore(backup))
        tx.add_step("DNS",
                     lambda: dns_switcher.apply(provider),
                     lambda backup: dns_switcher.restore(backup))
        results = tx.execute()   # {"TCP": {...}, "DNS": {...}}

    If DNS fails, TCP is automatically rolled back.
    """

    def __init__(self):
        self._steps: list[tuple[str, Callable[[], Any], Callable[[Any], None]]] = []
        self._completed: list[tuple[str, Any, Callable[[Any], None]]] = []

    def add_step(
        self,
        name: str,
        apply_fn: Callable[[], Any],
        rollback_fn: Callable[[Any], None],
    ) -> "ApplyTransaction":
        """Register an apply/rollback pair. Returns self for chaining."""
        self._steps.append((name, apply_fn, rollback_fn))
        return self

    def execute(self) -> dict[str, Any]:
        """
        Execute all steps in order.

        Returns a dict mapping step name -> apply result (backup).
        Raises ``TransactionError`` on failure after rolling back.
        """
        self._completed.clear()
        results: dict[str, Any] = {}

        for name, apply_fn, rollback_fn in self._steps:
            try:
                backup = apply_fn()
                self._completed.append((name, backup, rollback_fn))
                results[name] = backup
                logger.debug("Transaction step '%s' succeeded", name)
            except Exception as exc:
                logger.error("Transaction step '%s' failed: %s", name, exc)
                self._rollback()
                raise TransactionError(name, exc, list(results.keys())) from exc

        return results

    def _rollback(self) -> None:
        """Roll back completed steps in reverse order (best-effort)."""
        for name, backup, rollback_fn in reversed(self._completed):
            try:
                rollback_fn(backup)
                logger.info("Rolled back step '%s'", name)
            except Exception as exc:
                logger.warning("Rollback of step '%s' failed: %s", name, exc)
        self._completed.clear()


class TransactionError(Exception):
    """Raised when a transaction step fails after rollback."""

    def __init__(self, failed_step: str, cause: Exception, completed_steps: list[str]):
        self.failed_step = failed_step
        self.cause = cause
        self.completed_steps = completed_steps
        super().__init__(
            f"Step '{failed_step}' failed: {cause}. "
            f"Rolled back: {completed_steps or 'none'}"
        )
