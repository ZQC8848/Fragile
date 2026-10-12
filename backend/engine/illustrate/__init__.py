"""Illustration placeholder (story.md §12): until art exists the passage only carries a tableau id, which the
frontend shows as a text card. Tableaus hang on moments, never on beat boundaries."""

from __future__ import annotations

from typing import Any


def pick_tableau(steps: list[dict[str, Any]], ending: Any | None = None, opening_beat: Any | None = None) -> str | None:
    """The last tableau this passage reaches: a delivered step's, else the ending's."""
    for s in reversed(steps):
        if s.get("tableau"):
            return s["tableau"]
    if ending is not None and getattr(ending, "tableau", None):
        return ending.tableau
    return None
