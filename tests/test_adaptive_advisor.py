"""
Tests for recommendation queue helpers used by Adaptive Advisor UI wiring.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.adaptive_advisor import RecommendationQueue, merge_settings_patch
from core.adaptive_engine import AdaptiveRecommendation


def _rec(rec_id: str, created_at: float = 1.0) -> AdaptiveRecommendation:
    return AdaptiveRecommendation(
        id=rec_id,
        rule_name="Rule",
        severity="MEDIUM",
        title=f"Recommendation {rec_id}",
        message="Try this fix.",
        target="optimizer",
        settings_patch={"pause_bits": True},
        created_at=created_at,
    )


class TestRecommendationQueue:

    def test_add_deduplicates_by_id(self):
        queue = RecommendationQueue()

        assert queue.add(_rec("same")) is True
        assert queue.add(_rec("same")) is False

        assert [item["id"] for item in queue.list()] == ["same"]

    def test_list_returns_newest_first_dicts(self):
        queue = RecommendationQueue()
        queue.add(_rec("older", created_at=10.0))
        queue.add(_rec("newer", created_at=20.0))

        items = queue.list()

        assert [item["id"] for item in items] == ["newer", "older"]
        assert items[0]["settings_patch"] == {"pause_bits": True}

    def test_remove_returns_removed_recommendation(self):
        queue = RecommendationQueue()
        queue.add(_rec("dismiss-me"))

        removed = queue.remove("dismiss-me")

        assert removed["id"] == "dismiss-me"
        assert queue.list() == []

    def test_clear_removes_everything(self):
        queue = RecommendationQueue()
        queue.add(_rec("a"))
        queue.add(_rec("b"))

        queue.clear()

        assert queue.list() == []


def test_merge_settings_patch_does_not_mutate_current_settings():
    current = {"pause_windows_update": False, "pause_bits": False}
    patch = {"pause_bits": True}

    merged = merge_settings_patch(current, patch)

    assert merged == {"pause_windows_update": False, "pause_bits": True}
    assert current == {"pause_windows_update": False, "pause_bits": False}
