"""The beat pool: eligibility, entries, priority, must-follow and the ending table.

Every rule is evaluated over the state plus the transient `turn` namespace of the turn that just ended,
so a beat can be entered by what the player just did (the_admission's `accused` entry, second_crate).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.beats.loader import Beat, BeatLoadError, load_beats
from engine.dsl import truthy


def rule_ctx(state: dict[str, Any], turn: dict[str, Any] | None) -> dict[str, Any]:
    return {**state, "turn": turn or {}}


def completed(state: dict[str, Any], beat_id: str) -> bool:
    """Played to the end. Aborted beats stay selectable (interaction-design.md §6.2)."""
    return any(h["beat_id"] == beat_id and h.get("completed", True) for h in state.get("beat_history", []))


class BeatPool:
    def __init__(self, beats: list[Beat]):
        self.beats = beats
        self.by_id = {b.id: b for b in beats}

    @classmethod
    def from_dir(cls, directory: Path, state_vars: set[str] | None = None) -> BeatPool:
        return cls(load_beats(directory, state_vars))

    def reload(self, directory: Path, state_vars: set[str] | None = None) -> None:
        fresh = load_beats(directory, state_vars)
        generated = [b for b in self.beats if b.origin == "generated" and b.id not in {f.id for f in fresh}]
        self.beats = fresh + generated
        self.by_id = {b.id: b for b in self.beats}

    def add(self, beat: Beat) -> None:
        if beat.id in self.by_id:
            raise BeatLoadError(f"beat id {beat.id!r} already in pool")
        self.beats.append(beat)
        self.by_id[beat.id] = beat

    # -- rules ----------------------------------------------------------------
    @staticmethod
    def entry_for(beat: Beat, ctx: dict[str, Any]) -> dict[str, Any] | None:
        """The first entry whose `when` holds."""
        for entry, rule in zip(beat.entries, beat.compiled["entries"], strict=True):
            if truthy(rule, ctx):
                return entry
        return None

    def why_not(self, beat: Beat, state: dict[str, Any], turn: dict[str, Any] | None = None) -> str:
        """'' when eligible, otherwise the first reason it is not."""
        ctx = rule_ctx(state, turn)
        if completed(state, beat.id):
            return "already played"
        if not truthy(beat.compiled["preconditions"], ctx):
            return "preconditions false"
        if self.entry_for(beat, ctx) is None:
            return "no entry applies"
        if self.should_abort(beat, ctx):
            return "abort_if holds"
        return ""

    def eligible(self, state: dict[str, Any], turn: dict[str, Any] | None = None) -> list[Beat]:
        return [b for b in self.beats if self.why_not(b, state, turn) == ""]

    @staticmethod
    def priority(beat: Beat, ctx: dict[str, Any], entry: dict[str, Any] | None = None) -> float:
        p = sum(t["add"] for t in beat.compiled["priority_test"] if truthy(t["when"], ctx))
        if entry is not None:
            p += float(entry.get("priority_add", 0))
        return p

    @staticmethod
    def should_abort(beat: Beat, ctx: dict[str, Any]) -> bool:
        rule = beat.compiled["abort_if"]
        return bool(rule) and truthy(rule, ctx)

    def must_follow(self, state: dict[str, Any], turn: dict[str, Any] | None, exclude: str | None = None) -> Beat | None:
        """The triggered must-follow beat with the lowest rank (story.md §9.4), if any."""
        ctx = rule_ctx(state, turn)
        hits = [
            b for b in self.eligible(state, turn)
            if b.id != exclude and b.compiled["must_follow"] and truthy(b.compiled["must_follow"], ctx)
        ]
        return min(hits, key=lambda b: b.must_follow_rank or 99) if hits else None

    def ending_after_testimony(self, state: dict[str, Any], turn: dict[str, Any] | None) -> Beat | None:
        """The eligible ending with the lowest ending_rank (beat-script.md §4). Only once testimony is done."""
        if not completed(state, "testimony"):
            return None
        ends = [b for b in self.eligible(state, turn) if b.is_ending]
        return min(ends, key=lambda b: b.ending_rank or 99) if ends else None

    # -- views -----------------------------------------------------------------
    def shelf(self, state: dict[str, Any], turn: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Every beat with its standing right now, for the Console's beat shelf. Cheap: no scorers run."""
        ctx = rule_ctx(state, turn)
        out: list[dict[str, Any]] = []
        for b in self.beats:
            reason = self.why_not(b, state, turn)
            entry = self.entry_for(b, ctx) if reason == "" else None
            priority = self.priority(b, ctx, entry)
            out.append(
                {
                    "beat_id": b.id,
                    "title": b.title,
                    "type": b.type,
                    "origin": b.origin,
                    "tension_slope": b.tension_slope,
                    "minutes": b.minutes,
                    "weight": b.weight,
                    "priority": priority,
                    "must_follow_rank": b.must_follow_rank,
                    "entry": entry["id"] if entry else None,
                    "eligible": reason == "",
                    "reason": reason,
                    "played": completed(state, b.id),
                    "current": state.get("current_beat") == b.id,
                }
            )
        out.sort(key=lambda r: (not r["eligible"], -r["priority"], -r["weight"], r["beat_id"]))
        return out

    def endings(self) -> list[Beat]:
        return [b for b in self.beats if b.is_ending]

    def public(self) -> list[dict[str, Any]]:
        return [b.public() for b in self.beats]
