"""Recommendation logic for surfacing articles with different frames."""

from __future__ import annotations

from db import find_opposite_articles


def recommend_opposite(analysis: dict, limit: int = 3) -> list[dict]:
    """Recommend articles that overlap in issue tags but differ in frame."""
    issue_tags = analysis.get("issue_tags", []) if isinstance(analysis, dict) else []
    frame = analysis.get("frame", "") if isinstance(analysis, dict) else ""
    return find_opposite_articles(issue_tags=issue_tags, frame=frame, limit=limit)


def get_recommendations(analysis: dict, limit: int = 3) -> list[dict]:
    """Compatibility wrapper for the naming used in the current app draft."""
    return recommend_opposite(analysis, limit=limit)
