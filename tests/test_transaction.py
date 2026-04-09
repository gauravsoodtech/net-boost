"""
Tests for core/transaction.py — ApplyTransaction and TransactionError.
"""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.transaction import ApplyTransaction, TransactionError


class TestApplyTransaction:

    def test_successful_execution_returns_all_results(self):
        """All steps succeed — results dict contains every step's return value."""
        tx = ApplyTransaction()
        tx.add_step("A", lambda: {"backed_up": "a"}, lambda b: None)
        tx.add_step("B", lambda: {"backed_up": "b"}, lambda b: None)
        tx.add_step("C", lambda: 42, lambda b: None)

        results = tx.execute()

        assert results == {
            "A": {"backed_up": "a"},
            "B": {"backed_up": "b"},
            "C": 42,
        }

    def test_failure_rolls_back_completed_steps_in_reverse(self):
        """Step C fails → steps A and B are rolled back in reverse order (B then A)."""
        rollback_order = []

        def rollback_a(backup):
            rollback_order.append(("A", backup))

        def rollback_b(backup):
            rollback_order.append(("B", backup))

        tx = ApplyTransaction()
        tx.add_step("A", lambda: "backup_a", rollback_a)
        tx.add_step("B", lambda: "backup_b", rollback_b)
        tx.add_step("C", lambda: (_ for _ in ()).throw(RuntimeError("boom")), lambda b: None)

        with pytest.raises(TransactionError):
            tx.execute()

        assert rollback_order == [("B", "backup_b"), ("A", "backup_a")]

    def test_transaction_error_contains_metadata(self):
        """TransactionError exposes failed_step and completed_steps."""
        tx = ApplyTransaction()
        tx.add_step("DNS", lambda: {"dns": True}, lambda b: None)
        tx.add_step("TCP", lambda: (_ for _ in ()).throw(ValueError("bad")), lambda b: None)

        with pytest.raises(TransactionError) as exc_info:
            tx.execute()

        err = exc_info.value
        assert err.failed_step == "TCP"
        assert err.completed_steps == ["DNS"]
        assert isinstance(err.cause, ValueError)

    def test_empty_transaction_executes_without_error(self):
        """An empty transaction returns an empty dict and does not raise."""
        tx = ApplyTransaction()
        results = tx.execute()
        assert results == {}

    def test_rollback_failure_is_logged_not_raised(self, caplog):
        """If a rollback itself raises, it is logged but does not crash."""
        def bad_rollback(backup):
            raise OSError("rollback failed")

        tx = ApplyTransaction()
        tx.add_step("A", lambda: "bk", bad_rollback)
        tx.add_step("B", lambda: (_ for _ in ()).throw(RuntimeError("fail")), lambda b: None)

        with caplog.at_level(logging.WARNING):
            with pytest.raises(TransactionError):
                tx.execute()

        assert any("Rollback of step 'A' failed" in r.message for r in caplog.records)

    def test_chaining(self):
        """add_step returns self so calls can be chained."""
        tx = ApplyTransaction()
        result = tx.add_step("X", lambda: 1, lambda b: None)
        assert result is tx
