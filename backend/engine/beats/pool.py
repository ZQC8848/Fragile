"""The beat pool: eligibility, priority, dead-end checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.beats.loader import Beat, BeatLoadError, load_beats
from engine.dsl import truthy


class BeatPool:
    def __init__(self, beats: list[Beat]):
        self.beats = beats
        self.by_id = {b.id: b for b in beats}

    @classmethod
    def from_dir(cls, directory: Path, state_vars: set[str] | None = None) -> BeatPool:
        return cls(load_beats(directory, state_vars))

    def reload(self, directory: Path, state_vars: set[str] | None = None) -> None:
        fresh = load_beats(directory, state_vars)
        self.beats = fresh
        self.by_id = {b.id: b for b in fresh}

    def add(self, beat: Beat) -> None:
        if beat.id in self.by_id:
            raise BeatLoadError(f"beat id {beat.id!r} already in pool")
        self.beats.append(beat)
        self.by_id[beat.id] = beat

    # -- selection helpers ---------------------------------------------------
    def eligible(self, state: dict[str, Any]) -> list[Beat]:
        played = {h["beat_id"] for h in state.get("beat_history", [])}
        clock = float(state.get("clock_s", 0))
        out: list[Beat] = []
        for b in self.beats:
            # `repeatable` beats stay in the pool: interrupt beats (the cup at May's lips) have to be
            # able to fire every time the player triggers them, or the session dead-ends.
            if b.id in played and not b.raw.get("repeatable"):
                continue
            if b.raw.get("min_clock_s") is not None and clock < float(b.raw["min_clock_s"]):
                continue
            if truthy(b.compiled["preconditions"], state):
                out.append(b)
        return out

    @staticmethod
    def priority(beat: Beat, state: dict[str, Any]) -> float:
        p = 0.0
        for test in beat.compiled["priority_test"]:
            if truthy(test["when"], state):
                p += test["add"]
        force = beat.raw.get("force_after_clock_s")
        if force is not None and float(state.get("clock_s", 0)) >= float(force):
            p += 100.0
        return p

    def shelf(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Every beat with its standing right now, for the backstage shelf panel.

        Cheap on purpose: eligibility and `weight * (1 + priority)` are pure functions of the state, so
        this can be pushed on every backstage update. The scorers are NOT run here - they cost LLM calls
        and only make sense at an actual decision, where the decision log records them.
        """
        played = {h["beat_id"] for h in state.get("beat_history", [])}
        clock = float(state.get("clock_s", 0))
        out: list[dict[str, Any]] = []
        for b in self.beats:
            repeatable = bool(b.raw.get("repeatable"))
            min_clock = b.raw.get("min_clock_s")
            reason = ""
            if b.id in played and not repeatable:
                reason = "already played"
            elif min_clock is not None and clock < float(min_clock):
                reason = f"waits for clock {float(min_clock):.0f}s"
            elif not truthy(b.compiled["preconditions"], state):
                reason = "preconditions false"
            priority = self.priority(b, state)
            out.append(
                {
                    "beat_id": b.id,
                    "title": b.title,
                    "type": b.type,
                    "origin": b.origin,
                    "tension_slope": b.tension_slope,
                    "weight": b.weight,
                    "priority": priority,
                    "base_score": b.weight * (1.0 + priority),
                    "eligible": reason == "",
                    "reason": reason,
                    "repeatable": repeatable,
                    "played": b.id in played,
                    "aborts_now": self.should_abort(b, state),
                }
            )
        out.sort(key=lambda r: (not r["eligible"], -r["base_score"], r["beat_id"]))
        return out

    @staticmethod
    def should_abort(beat: Beat, state: dict[str, Any]) -> bool:
        rule = beat.compiled["abort_if"]
        return bool(rule) and truthy(rule, state)

    def spine(self) -> list[Beat]:
        return [b for b in self.beats if b.type == "spine"]

    def endings(self) -> list[Beat]:
        return [b for b in self.beats if b.type == "ending"]

    def public(self) -> list[dict[str, Any]]:
        return [b.public() for b in self.beats]
