"""World rules: an action unit (verb, target[, arg]) becomes a result in the world (data/interactions.yaml;
interaction-design.md §6.6, §8).

Actions are attempts. Each one ends as:
    done     it happened; `effects` changed the world, `note` says what the player now perceives
    free     a gesture the world has no rule for (looking at someone); nothing changes, the narrator renders it
    failed   it cannot be attempted here (wrong room, nothing like that here); `note` says why
    blocked  the world (`needs`) or a present NPC (`blockers`) stopped it; a blocking NPC loses composure

After the action the hosts may follow the player (`follow`) and `private_turns` is recounted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.dsl import apply_effects, compile_expr, truthy
from engine.paths import DATA_DIR
from engine.state.schema import StateSchema

HOSTS = ("julian", "mia")
NPCS = ("julian", "mia", "nora")


@dataclass
class WorldResult:
    action: dict[str, Any] | None
    status: str = "none"  # none | done | free | failed | blocked
    blocked_by: str | None = None
    note: str | None = None
    effects: dict[str, Any] = field(default_factory=dict)
    #: facts the world effects added to `revealed`
    reveals: list[str] = field(default_factory=list)
    follow_notes: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "status": self.status,
            "blocked_by": self.blocked_by,
            "note": self.note,
            "effects": self.effects,
            "reveals": self.reveals,
            "follow_notes": self.follow_notes,
            "moved": self.moved,
        }


def _rule(src: str | None) -> Any:
    return compile_expr(src) if src else True


class WorldRules:
    def __init__(self, schema: StateSchema, raw: dict[str, Any]):
        self.schema = schema
        self.raw = raw
        self.block_cost = float(raw.get("block_cost", 0.15))
        self.rooms: dict[str, dict[str, Any]] = raw["rooms"]
        self.follow = [{**f, "_when": _rule(f["when"])} for f in raw.get("follow", [])]
        self.movement: dict[str, dict[str, Any]] = {
            verb: {target: self._compile_spec(spec) for target, spec in (targets or {}).items()}
            for verb, targets in raw.get("movement", {}).items()
        }
        self.objects: dict[str, dict[str, Any]] = {}
        for name, obj in raw.get("objects", {}).items():
            actions = {verb: self._compile_spec(spec) for verb, spec in (obj.get("actions") or {}).items()}
            self.objects[name] = {**obj, "actions": actions}

    @classmethod
    def from_file(cls, schema: StateSchema, path: Path | None = None) -> WorldRules:
        return cls(schema, yaml.safe_load((path or DATA_DIR / "interactions.yaml").read_text(encoding="utf-8")))

    def _compile_spec(self, spec: dict[str, Any] | None) -> dict[str, Any]:
        spec = dict(spec or {})
        spec["_when"] = _rule(spec.get("when"))
        spec["_needs"] = _rule(spec.get("needs"))
        spec["_blockers"] = [{**b, "_when": _rule(b["when"])} for b in spec.get("blockers") or []]
        for key in (spec.get("effects") or {}):
            if key.split(".")[0] not in self.schema.props:
                raise KeyError(f"interactions.yaml: unknown state variable {key!r}")
        return spec

    # -- views ------------------------------------------------------------------------------
    @staticmethod
    def present(state: dict[str, Any]) -> list[str]:
        """NPCs in the player's room: the only ones who see and hear the player (interaction-design.md §8.3)."""
        room = state.get("player_room")
        if room == "outside":  # out of the flat; Nora's "outside" only means she has not arrived
            return []
        return [n for n in NPCS if state.get(f"{n}_room") == room]

    def object_topics(self) -> dict[str, dict[str, Any]]:
        """{object: {topic, where}} for the encoder."""
        return {name: {"topic": o.get("topic"), "where": o.get("where")} for name, o in self.objects.items()}

    def perceivable(self, state: dict[str, Any]) -> list[str]:
        """Objects the player can see from where they stand."""
        room = state.get("player_room")
        return [n for n, o in self.objects.items() if o.get("where") and room in o["where"]]

    # -- applying an action -------------------------------------------------------------------
    def apply(self, state: dict[str, Any], action: dict[str, Any] | None, turn: dict[str, Any]) -> tuple[dict[str, Any], WorldResult]:
        if not action:
            return state, WorldResult(None)
        verb, target, arg = action.get("verb"), action.get("target"), action.get("arg")
        ctx = {**state, "turn": turn, "target": target, "arg": arg}
        if verb == "go_to":
            return self._go_to(state, ctx, action, target)
        if verb == "take_aside":
            return self._take_aside(state, ctx, action, target, arg)
        if verb == "leave":
            return self._attempt(state, ctx, action, self.movement["leave"]["front_door"], "front_door",
                                 fail_note="The front door is in the hall.")
        obj = self.objects.get(target or "")
        if obj is None:
            return state, WorldResult(action, "failed", note="There's nothing like that here.")
        where = obj.get("where")
        if where and state.get("player_room") not in where:
            return state, WorldResult(action, "failed", note=f"There's no {target.replace('_', ' ')} here.")
        spec = obj["actions"].get(verb)
        if spec is None:
            return state, WorldResult(action, "free")
        if spec.get("arg") == "required" and not arg:
            return state, WorldResult(action, "failed", note="You'd have to say what.")
        return self._attempt(state, ctx, action, spec, target)

    def _go_to(self, state, ctx, action, target):
        here = state.get("player_room")
        if target == "outside":
            return self._attempt(state, ctx, {**action, "verb": "leave", "target": "front_door"},
                                 self.movement["leave"]["front_door"], "front_door", fail_note="The front door is in the hall.")
        if target not in self.rooms:
            return state, WorldResult(action, "failed", note="There's no such room here.")
        if target == here:
            return state, WorldResult(action, "free")
        if target not in self.rooms.get(here, {}).get("adjacent", []):
            via = next((r for r in self.rooms.get(here, {}).get("adjacent", []) if target in self.rooms[r].get("adjacent", [])), None)
            return state, WorldResult(action, "failed", note=f"One room at a time: the way there is through the {via or 'flat'}.")
        spec = self.movement.get("go_to", {}).get(target) or {"_when": True, "_needs": True, "_blockers": []}
        spec = {**spec, "effects": {"player_room": target, **(spec.get("effects") or {})}}
        return self._attempt(state, ctx, action, spec, target)

    def _take_aside(self, state, ctx, action, target, arg):
        spec = self.movement.get("take_aside", {}).get(target or "")
        if spec is None:
            return state, WorldResult(action, "failed", note="You can only take Julian or Mia aside.")
        if not truthy(spec["_when"], ctx):
            return state, WorldResult(action, "failed", note=f"{target.capitalize()} isn't here.")
        if arg not in ("kitchen", "balcony", "hall", "living"):
            return state, WorldResult(action, "failed", note="Where to?")
        other = "mia" if target == "julian" else "julian"
        effects: dict[str, Any] = {"player_room": arg, f"{target}_room": arg}
        if state.get(f"{other}_room") == state.get("player_room") and arg != state.get("player_room"):
            effects[f"{other}_composure"] = spec.get("left_behind_composure", "-0.1")
        new = apply_effects(state, effects, self.schema.props)
        return new, WorldResult(action, "done", effects=effects, moved=[target])

    def _attempt(self, state, ctx, action, spec, target, fail_note: str | None = None):
        if not truthy(spec["_when"], ctx):
            return state, WorldResult(action, "failed", note=spec.get("fail_note") or fail_note or "That doesn't work right now.")
        if not truthy(spec["_needs"], ctx):
            return state, WorldResult(action, "blocked", blocked_by="world", note=spec.get("blocked_note"))
        for b in spec["_blockers"]:
            if truthy(b["_when"], ctx):
                who = b["who"]
                effects = {f"{who}_composure": f"-{self.block_cost}"} if f"{who}_composure" in self.schema.props else {}
                new = apply_effects(state, effects, self.schema.props)
                return new, WorldResult(action, "blocked", blocked_by=who, note=spec.get("blocked_note"), effects=effects)
        effects = dict(spec.get("effects") or {})
        if spec.get("classify") == "nora_told" and ctx["turn"].get("nora_answer") in ("truth", "lie"):
            effects["nora_told"] = ctx["turn"]["nora_answer"]
        new = apply_effects(state, effects, self.schema.props)
        reveals = [f for f in new.get("revealed", []) if f not in state.get("revealed", [])]
        return new, WorldResult(action, "done", note=spec.get("note"), effects=effects, reveals=reveals)

    # -- after the action ----------------------------------------------------------------------
    def settle(self, state: dict[str, Any], result: WorldResult) -> tuple[dict[str, Any], WorldResult]:
        """Hosts follow the player (interaction-design.md §8.2), then `private_turns` is recounted."""
        state = dict(state)
        state["private_turns"] = self._private_turns(state)
        for f in self.follow:
            who = f["move"]
            if state.get(f"{who}_room") == state.get("player_room"):
                continue
            if truthy(f["_when"], {**state, "turn": {}}):
                state[f"{who}_room"] = state["player_room"]
                result.follow_notes.append(f["note"])
                result.moved.append(who)
                state["private_turns"] = self._private_turns(state, reset=True)
        return state, result

    @staticmethod
    def _private_turns(state: dict[str, Any], reset: bool = False) -> int:
        room = state.get("player_room")
        with_player = [h for h in HOSTS if state.get(f"{h}_room") == room]
        if len(with_player) == 1 and state.get("nora_room") != room and not reset:
            return int(state.get("private_turns", 0)) + 1
        return 0
