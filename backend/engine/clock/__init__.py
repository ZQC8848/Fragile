"""The story clock (interaction-design.md §7, data/clock.yaml).

Time is a state variable, not real time. `story_min` moves only when a beat ends, by that beat's
`minutes` (or the phase default). Crossing an event's minute fires it in the same turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.paths import DATA_DIR

__all__ = ["ClockEvent", "StoryClock"]


@dataclass(frozen=True)
class ClockEvent:
    id: str
    at_min: float
    effects: dict[str, Any] = field(default_factory=dict)
    phone: dict[str, Any] | None = None
    hold_beat_choice: bool = False
    unanswered: dict[str, Any] | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> ClockEvent:
        return cls(
            id=raw["id"],
            at_min=float(raw["at_min"]),
            effects=dict(raw.get("effects") or {}),
            phone=raw.get("phone"),
            hold_beat_choice=bool(raw.get("hold_beat_choice", False)),
            unanswered=raw.get("unanswered"),
        )

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "at_min": self.at_min, "phone": self.phone, "hold_beat_choice": self.hold_beat_choice}


class StoryClock:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.phases: dict[str, dict[str, Any]] = raw["phases"]
        self.events = sorted((ClockEvent.from_raw(e) for e in raw.get("events", [])), key=lambda e: e.at_min)
        self.safety_cap_turns = int(raw.get("safety_cap_turns", 40))
        self.fast_forward_gaps = bool(raw.get("fast_forward_gaps", True))
        lo, hi = raw.get("generated_minutes_range", [0.5, 2.0])
        self.generated_range = (float(lo), float(hi))

    @classmethod
    def from_file(cls, path: Path | None = None) -> StoryClock:
        path = path or DATA_DIR / "clock.yaml"
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    # -- phases ---------------------------------------------------------------
    def phase_of(self, story_min: float) -> str:
        for name in ("early", "mid"):
            until = self.phases[name].get("until_min")
            if until is not None and story_min < float(until):
                return name
        return "late"

    def default_minutes(self, story_min: float) -> float:
        return float(self.phases[self.phase_of(story_min)]["default_minutes"])

    def passage_words(self, story_min: float) -> tuple[int, int]:
        lo, hi = self.phases[self.phase_of(story_min)]["passage_words"]
        return int(lo), int(hi)

    def minutes_for(self, beat_minutes: float | None, story_min: float) -> float:
        """What a beat ending now adds to the clock."""
        return float(beat_minutes) if beat_minutes is not None else self.default_minutes(story_min)

    def minutes_in_range(self, minutes: float, story_min: float) -> bool:
        """Hard check for generated beats: within [0.5, 2] x the phase default."""
        d = self.default_minutes(story_min)
        return self.generated_range[0] * d <= float(minutes) <= self.generated_range[1] * d

    # -- events ---------------------------------------------------------------
    def crossed(self, before: float, after: float) -> list[ClockEvent]:
        """Events whose minute lies in (before, after]."""
        return [e for e in self.events if before < e.at_min <= after]

    def next_pending(self, story_min: float) -> ClockEvent | None:
        return next((e for e in self.events if e.at_min > story_min), None)

    def event(self, event_id: str) -> ClockEvent | None:
        return next((e for e in self.events if e.id == event_id), None)
