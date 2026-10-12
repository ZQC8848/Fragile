"""Target tension arc over story minutes (story.md §6.2, data/tension_curve.yaml).

The curve is a list of (story_min, tension) points, linear in between. The DM's target for a candidate beat
is the tension the arc wants when that beat would end, minus the tension now (tension_curve.yaml header).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from engine.paths import DATA_DIR


class TensionArc:
    def __init__(self, points: list[tuple[float, float]]):
        if not points:
            raise ValueError("tension arc needs at least one point")
        self.points = sorted((float(x), float(y)) for x, y in points)

    @classmethod
    def from_file(cls, path: Path | None = None) -> TensionArc:
        data = yaml.safe_load((path or DATA_DIR / "tension_curve.yaml").read_text(encoding="utf-8")) or {}
        return cls([tuple(p) for p in data["points"]])

    def target_at(self, story_min: float) -> float:
        pts = self.points
        if story_min <= pts[0][0]:
            return pts[0][1]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
            if story_min <= x1:
                return y0 + (y1 - y0) * (story_min - x0) / (x1 - x0)
        return pts[-1][1]

    def target_delta(self, story_min: float, minutes: float, tension_now: float) -> float:
        """Desired tension change if a beat of `minutes` starts now."""
        return self.target_at(story_min + minutes) - tension_now

    def distance(self, trace: list[tuple[float, float]]) -> float:
        """Mean absolute deviation of a (story_min, tension) trace from the arc."""
        if not trace:
            return 0.0
        return sum(abs(t - self.target_at(m)) for m, t in trace) / len(trace)
