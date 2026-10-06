"""World rules: player movement and object interactions -> state changes (data-driven, interactions.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.dsl import apply_effects, compile_expr, truthy
from engine.state.schema import StateSchema

INDOOR_ZONES = {"entrance", "guest_table", "bar", "counter", "kitchen_door", "back_corner"}


@dataclass
class InteractionOutcome:
    applied: bool
    state: dict[str, Any]
    object_state: str | None = None
    note: str | None = None
    reason: str = ""
    effects: dict[str, Any] = field(default_factory=dict)


class WorldRules:
    def __init__(self, schema: StateSchema, path: Path):
        self.schema = schema
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self.rules: dict[str, dict[str, dict[str, Any]]] = {}
        for obj, actions in raw.items():
            self.rules[obj] = {}
            for action, spec in (actions or {}).items():
                spec = dict(spec or {})
                spec["_when"] = compile_expr(spec.get("when", "true"))
                # validate effect targets early
                for var in (spec.get("effects") or {}):
                    if var not in schema.props:
                        raise KeyError(f"interactions.yaml {obj}.{action}: unknown state var {var!r}")
                self.rules[obj][action] = spec

    def actions_for(self, obj: str, state: dict[str, Any]) -> list[str]:
        return [a for a, spec in self.rules.get(obj, {}).items() if truthy(spec["_when"], state)]

    def apply_interaction(self, state: dict[str, Any], target: str, action: str) -> InteractionOutcome:
        spec = self.rules.get(target, {}).get(action)
        if spec is None:
            return InteractionOutcome(False, state, reason=f"no rule for {target}.{action}")
        if not truthy(spec["_when"], state):
            return InteractionOutcome(False, state, reason=f"{target}.{action} not allowed in current state")
        new = apply_effects(state, spec.get("effects") or {}, self.schema.props)
        new["last_interaction"] = {"target": target, "action": action}
        return InteractionOutcome(
            True, new, object_state=spec.get("object_state"), note=spec.get("note"), effects=spec.get("effects") or {}
        )

    def apply_move(self, state: dict[str, Any], zone: str) -> dict[str, Any]:
        new = dict(state)
        new["may_zone"] = zone
        if zone == "guest_table" and new.get("danger_proximity", 0) < 1 and new.get("glass") not in ("drunk", "at_bar"):
            new["danger_proximity"] = 1
        if zone != "guest_table" and new.get("glass") in ("on_table", "moved") and new.get("danger_proximity", 0) == 1:
            new["danger_proximity"] = 0
        return new

    def present_actors(self, state: dict[str, Any]) -> list[str]:
        """Actors visible to the player right now (indoor vs street)."""
        may_in = state.get("may_zone") in INDOOR_ZONES
        out = ["may"]
        if may_in and state.get("lin_zone") in INDOOR_ZONES:
            out.append("lin")
        if state.get("guest_zone") in INDOOR_ZONES and may_in:
            out.append("guest")
        return out
