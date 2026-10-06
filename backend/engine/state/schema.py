"""Story state as data: schema loading, initial state, validation, textualization, diff.

Constraint B (docs/backend-design.md section 2): the state schema is a versioned JSON Schema file
under <repo>/schemas/state_v<N>.json. Nothing in the engine hard-codes variable names except the
few structural ones listed in STRUCTURAL (beat_history, clock_s, ...).
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "schemas"

CURRENT_STATE_VERSION = 1

# Variables the engine itself reads/writes. Everything else is opaque data for rules and scorers.
STRUCTURAL = {
    "schema_version",
    "beat_history",
    "consecutive_generated",
    "story_phase",
    "clock_s",
    "ending",
    "last_discourse_act",
    "last_interaction",
}

INDOOR_ZONES = {"entrance", "guest_table", "bar", "counter", "kitchen_door", "back_corner"}


class StateSchema:
    def __init__(self, version: int = CURRENT_STATE_VERSION):
        self.version = version
        path = SCHEMAS_DIR / f"state_v{version}.json"
        self.raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        self.props: dict[str, Any] = self.raw["properties"]
        self._validator = jsonschema.Draft202012Validator(self.raw)

    # -- lifecycle -------------------------------------------------------
    def initial_state(self) -> dict[str, Any]:
        """The opening situation of Wrongest Person: Lin alone in the closed restaurant, May outside."""
        return {
            "schema_version": self.version,
            "tension": 1,
            "lin_composure": 1.0,
            "may_suspicion": 0,
            "may_trust_lin": 1,
            "danger_proximity": 0,
            "guest_pressure": 0,
            "revealed": [],
            "glass": "on_table",
            "gun": "hidden",
            "envelope": "sealed",
            "door": "closed",
            "may_zone": "street",
            "lin_zone": "guest_table",
            "guest_zone": "absent",
            "beat_history": [],
            "consecutive_generated": 0,
            "story_phase": "early",
            "clock_s": 0.0,
            "ending": None,
            "last_discourse_act": None,
            "last_interaction": None,
        }

    def validate(self, state: dict[str, Any]) -> list[str]:
        return [e.message for e in self._validator.iter_errors(state)]

    def assert_valid(self, state: dict[str, Any]) -> None:
        errs = self.validate(state)
        if errs:
            raise ValueError("invalid state: " + "; ".join(errs))

    # -- derived ----------------------------------------------------------
    @staticmethod
    def derive_phase(state: dict[str, Any]) -> str:
        if state.get("ending"):
            return "ended"
        n = len(state.get("beat_history", []))
        if state.get("guest_pressure", 0) >= 2 or n >= 8:
            return "late"
        if n >= 3:
            return "mid"
        return "early"

    def refresh_derived(self, state: dict[str, Any]) -> dict[str, Any]:
        state = dict(state)
        state["story_phase"] = self.derive_phase(state)
        return state

    # -- textualization (scorer input, constraint A) ----------------------
    def textualize(self, state: dict[str, Any]) -> str:
        """Flat, stable, human-readable rendering. Order follows the schema so re-training data is
        consistent across sessions. Structural lists are summarized, not dumped."""
        parts: list[str] = []
        for name in self.props:
            if name in ("schema_version", "last_interaction"):
                continue
            val = state.get(name)
            if name == "beat_history":
                ids = [h["beat_id"] for h in (val or [])]
                parts.append(f"beats_played={','.join(ids) if ids else 'none'}")
            elif isinstance(val, list):
                parts.append(f"{name}={','.join(map(str, val)) if val else 'none'}")
            elif isinstance(val, float):
                parts.append(f"{name}={val:.2f}")
            else:
                parts.append(f"{name}={val}")
        li = state.get("last_interaction")
        if li:
            parts.append(f"last_interaction={li.get('action')}:{li.get('target')}")
        return "; ".join(parts)

    @staticmethod
    def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in set(before) | set(after):
            if k == "beat_history":
                continue
            if before.get(k) != after.get(k):
                out[k] = {"from": before.get(k), "to": after.get(k)}
        return out

    def copy(self, state: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(state)
