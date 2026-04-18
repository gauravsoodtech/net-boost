"""
Small pure-Python helpers for Adaptive Advisor recommendation state.
"""

from __future__ import annotations

from core.adaptive_engine import AdaptiveRecommendation


class RecommendationQueue:
    """Session-local pending recommendation store."""

    def __init__(self):
        self._items: dict[str, dict] = {}

    def add(self, recommendation: AdaptiveRecommendation | dict) -> bool:
        item = _as_dict(recommendation)
        rec_id = item["id"]
        if rec_id in self._items:
            return False
        self._items[rec_id] = item
        return True

    def remove(self, recommendation_id: str) -> dict | None:
        return self._items.pop(recommendation_id, None)

    def clear(self) -> None:
        self._items.clear()

    def get(self, recommendation_id: str) -> dict | None:
        item = self._items.get(recommendation_id)
        return dict(item) if item else None

    def list(self) -> list[dict]:
        return [
            dict(item)
            for item in sorted(
                self._items.values(),
                key=lambda rec: rec.get("created_at", 0.0),
                reverse=True,
            )
        ]


def merge_settings_patch(current: dict, patch: dict) -> dict:
    merged = dict(current)
    merged.update(patch)
    return merged


def _as_dict(recommendation: AdaptiveRecommendation | dict) -> dict:
    if isinstance(recommendation, AdaptiveRecommendation):
        return recommendation.to_dict()
    return dict(recommendation)
