"""Story state as data: schema loading, initial state, validation, textualization, diff.

The state schema is a versioned JSON Schema file under <repo>/schemas/state_v<N>.json. Every property
carries a `default`, and the initial state is built from those defaults (beat-script.md §0.1), so nothing
here hard-codes the story's variables except the structural ones the engine itself moves.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import jsonschema

from engine.paths import REPO_ROOT, SCHEMAS_DIR

CURRENT_STATE_VERSION = 2

# Variables the engine itself reads/writes. Everything else is opaque data for rules and scorers.
STRUCTURAL = {
    "schema_version",
    "story_min",
    "turn_count",
    "story_phase",
    "current_beat",
    "beat_step",
    "beat_turns",
    "beat_history",
    "consecutive_generated",
    "silence_streak",
    "private_turns",
    "claims",
    "heard_by",
    "ending",
}

#: story_min thresholds of the phases (interaction-design.md §7.1); data/clock.yaml carries the same numbers
PHASE_BOUNDS = (("early", 6.0), ("mid", 12.0))

__all__ = ["CURRENT_STATE_VERSION", "REPO_ROOT", "SCHEMAS_DIR", "STRUCTURAL", "StateSchema"]


class StateSchema:
    def __init__(self, version: int = CURRENT_STATE_VERSION):
        self.version = version
        # a module global read at call time, so tests can point SCHEMAS_DIR at a fixture directory
        path = SCHEMAS_DIR / f"state_v{version}.json"
        self.raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        self.props: dict[str, Any] = self.raw["properties"]
        self.defs: dict[str, Any] = self.raw.get("$defs", {})
        self._validator = jsonschema.Draft202012Validator(self.raw)

    # -- lifecycle -------------------------------------------------------
    def initial_state(self) -> dict[str, Any]:
        """Every property at its schema `default`."""
        missing = [name for name, prop in self.props.items() if "default" not in prop]
        if missing:
            raise ValueError(f"state_v{self.version}.json: no default for {missing}")
        return {name: deepcopy(prop["default"]) for name, prop in self.props.items()}

    def validate(self, state: dict[str, Any]) -> list[str]:
        return [f"{list(e.absolute_path)}: {e.message}" for e in self._validator.iter_errors(state)]

    def assert_valid(self, state: dict[str, Any]) -> None:
        errs = self.validate(state)
        if errs:
            raise ValueError("invalid state: " + "; ".join(errs))

    def enum(self, name: str) -> list[str]:
        """Values of a $defs enum (Fact, Room, Npc, Addressee)."""
        return list(self.defs[name]["enum"])

    # -- derived ----------------------------------------------------------
    @staticmethod
    def derive_phase(state: dict[str, Any]) -> str:
        if state.get("ending"):
            return "ended"
        m = float(state.get("story_min", 0))
        for phase, until in PHASE_BOUNDS:
            if m < until:
                return phase
        return "late"

    def refresh_derived(self, state: dict[str, Any]) -> dict[str, Any]:
        state = dict(state)
        state["story_phase"] = self.derive_phase(state)
        return state

    # -- textualization (scorer input: never beat ids as features beyond the history summary) ---------
    def textualize(self, state: dict[str, Any]) -> str:
        """Flat, stable, human-readable rendering in schema order, so training data stays consistent across
        sessions. Bookkeeping lists are summarized, not dumped."""
        parts: list[str] = []
        for name in self.props:
            if name in ("schema_version", "heard_by", "beat_step", "beat_turns", "consecutive_generated"):
                continue
            val = state.get(name)
            if name == "beat_history":
                ids = [h["beat_id"] for h in (val or []) if h.get("completed", True)]
                parts.append(f"beats_played={','.join(ids) if ids else 'none'}")
            elif name == "claims":
                facts = sorted({c["fact"] for c in (val or [])})
                parts.append(f"claims={','.join(facts) if facts else 'none'}")
            elif name == "topic_tier":
                parts.append("topic_tier=" + ",".join(f"{k}:{v}" for k, v in (val or {}).items()))
            elif isinstance(val, list):
                parts.append(f"{name}={','.join(map(str, val)) if val else 'none'}")
            elif isinstance(val, float):
                parts.append(f"{name}={val:.2f}")
            else:
                parts.append(f"{name}={val}")
        return "; ".join(parts)

    @staticmethod
    def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in set(before) | set(after):
            if k == "beat_history":
                continue
            a, b = before.get(k), after.get(k)
            if isinstance(a, dict) and isinstance(b, dict) and k != "heard_by":
                for sub in set(a) | set(b):
                    if a.get(sub) != b.get(sub):
                        out[f"{k}.{sub}"] = {"from": a.get(sub), "to": b.get(sub)}
            elif a != b:
                out[k] = {"from": a, "to": b}
        return out

    def copy(self, state: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(state)

