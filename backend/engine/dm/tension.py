"""Target tension arc.

The authored arc is a list of target tension values indexed by decision number (0 = the first
beat). `target_slope(k)` is what Façade's scoring compares each candidate's `tension_slope` to.
Loaded from backend/data/tension_curve.yaml so the writer can reshape it without code changes.
"""

from __future__ import annotations

from pathlib import Path

import yaml

DEFAULT_CURVE = [1, 1, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5, 4, 3, 2, 2, 2]


class TensionArc:
    def __init__(self, targets: list[float] | None = None):
        self.targets = [float(t) for t in (targets or DEFAULT_CURVE)]

    @classmethod
    def from_file(cls, path: Path) -> TensionArc:
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(data.get("targets"))

    def target_at(self, k: int) -> float:
        if k < 0:
            return self.targets[0]
        if k >= len(self.targets):
            return self.targets[-1]
        return self.targets[k]

    def target_slope(self, k: int) -> float:
        """Desired change in tension produced by the beat chosen at decision k."""
        return self.target_at(k + 1) - self.target_at(k)

    def distance(self, actual: list[float]) -> float:
        """Mean absolute deviation between an actual per-decision tension trace and the target."""
        if not actual:
            return 0.0
        return sum(abs(a - self.target_at(i)) for i, a in enumerate(actual)) / len(actual)
