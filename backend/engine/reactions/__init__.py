"""The reaction layer (interaction-design.md §5, data/reactions.yaml): a deterministic rule table, no LLM.

Every turn:
  1. `rules` fire: social and emotional deltas from what the player did, whatever reaction is chosen;
  2. candidates are collected: the current beat's local mix-ins (priority 10) and the global reactions whose
     `when` holds and whose responder is in the room; `once` reactions already used are skipped;
  3. the highest priority is the primary reaction; at most one secondary from a different responder with a
     lower priority (deflections are never secondary: they would only be noise; a local mix-in gets none: it
     already answers what the player did, and a second take on the same thing would only repeat it);
  4. effects: rules + primary + secondary; topic tiers only rise one step and never past the phase cap.

The per-variable cap (each variable moves at most one step per turn) is applied by the turn loop over the world
effects and these together: `cap_deltas`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.beats import BeatRun, rule_ctx
from engine.dsl import compile_expr, truthy
from engine.paths import DATA_DIR
from engine.world import WorldRules

HOSTS = ("julian", "mia")
NPCS = ("julian", "mia", "nora")
#: the lowest priority a secondary reaction may have (social and up)
MIN_SECONDARY_PRIORITY = 3


@dataclass
class Reaction:
    id: str
    type: str
    priority: float
    do: str
    responder: str | None
    effects: dict[str, Any] = field(default_factory=dict)
    once: bool = True
    topic: str | None = None
    tier: int | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "priority": self.priority,
            "responder": self.responder,
            "do": self.do,
            "effects": self.effects,
            "topic": self.topic,
            "tier": self.tier,
        }


@dataclass
class ReactionResult:
    rules: list[dict[str, Any]]
    candidates: list[Reaction]
    primary: Reaction | None
    secondary: Reaction | None
    effects: list[dict[str, Any]]
    #: candidates dropped because their responder was not in the room
    unavailable: list[str] = field(default_factory=list)

    @property
    def primary_priority(self) -> float:
        return self.primary.priority if self.primary else 0.0

    def chosen(self) -> list[Reaction]:
        return [r for r in (self.primary, self.secondary) if r]

    def public(self) -> dict[str, Any]:
        return {
            "rules": [r["id"] for r in self.rules],
            "candidates": [{"id": c.id, "priority": c.priority, "responder": c.responder} for c in self.candidates],
            "primary": self.primary.public() if self.primary else None,
            "secondary": self.secondary.public() if self.secondary else None,
            "unavailable": self.unavailable,
        }


class ReactionLayer:
    def __init__(self, raw: dict[str, Any]):
        self.raw = raw
        self.priorities: dict[str, float] = {k: float(v) for k, v in raw["priorities"].items()}
        self.tier_cap: dict[str, int] = raw["phase_tier_cap"]
        self.per_turn_cap: dict[str, float] = {k: float(v) for k, v in raw["per_turn_cap"].items()}
        self.topic_owner: dict[str, str] = raw["topic_owner"]
        self.rules = [{**r, "_when": compile_expr(r["when"])} for r in raw.get("rules", [])]
        self.reactions = [{**r, "_when": compile_expr(r["when"])} for r in raw.get("reactions", [])]
        rec = raw.get("recovery")
        self.recovery = {**rec, "_when": compile_expr(rec["when"])} if rec else None

    @classmethod
    def from_file(cls, path: Path | None = None) -> ReactionLayer:
        return cls(yaml.safe_load((path or DATA_DIR / "reactions.yaml").read_text(encoding="utf-8")))

    # ------------------------------------------------------------------ selection
    def select(
        self,
        state: dict[str, Any],
        turn: dict[str, Any],
        run: BeatRun | None,
        used: set[str],
        last_speaker: str | None = None,
    ) -> ReactionResult:
        ctx = rule_ctx(state, turn)
        present = WorldRules.present(state)
        fired = [r for r in self.rules if truthy(r["_when"], ctx)]

        cands: list[Reaction] = []
        unavailable: list[str] = []
        if run is not None:
            for i, (m, rule) in enumerate(zip(run.beat.raw.get("mix_in") or [], run.beat.compiled["mix_in"], strict=True)):
                rid = f"{run.beat.id}#mix{i}"
                once = m.get("once", True)
                if (once and rid in used) or not truthy(rule, ctx):
                    continue
                cands.append(Reaction(rid, "local", self.priorities["local"], m["do"], None, dict(m.get("effects") or {}), once))
        for r in self.reactions:
            once = r.get("once", True)
            if (once and r["id"] in used) or not truthy(r["_when"], ctx):
                continue
            who = self.responder(r, state, turn, present, last_speaker)
            if who is None:
                unavailable.append(r["id"])
                continue
            cands.append(Reaction(r["id"], r["type"], self.priorities[r["type"]], r["do"], who,
                                  dict(r.get("effects") or {}), once, r.get("topic"), r.get("tier")))

        # stable: the file order breaks ties (local mix-ins first)
        ranked = sorted(cands, key=lambda c: -c.priority)
        primary = ranked[0] if ranked else None
        secondary = None
        if primary is not None and primary.type != "local":
            secondary = next(
                (c for c in ranked[1:] if c.priority < primary.priority and c.priority >= MIN_SECONDARY_PRIORITY
                 and c.responder and c.responder != primary.responder),
                None,
            )
        effects = [{"source": f"rule:{r['id']}", "effects": dict(r.get("effects") or {})} for r in fired]
        for c in (primary, secondary):
            if c is not None and c.effects:
                effects.append({"source": f"reaction:{c.id}", "effects": self._tier_safe(c.effects, state)})
        return ReactionResult(fired, ranked, primary, secondary, effects, unavailable)

    def responder(self, r: dict[str, Any], state: dict[str, Any], turn: dict[str, Any], present: list[str], last_speaker: str | None) -> str | None:
        """Who performs a reaction (interaction-design.md §5.3); None when nobody suitable is in the room."""
        spec = r["responder"]
        addressee = turn.get("addressee")
        if spec in NPCS:
            return spec if spec in present else None
        if spec == "addressee":
            return addressee if addressee in present else None
        if spec == "owner":
            if addressee in present and addressee in HOSTS:
                return addressee
            owner = self.topic_owner.get(r.get("topic") or "", "any")
            if owner == "less_composed":
                hosts = [h for h in HOSTS if h in present]
                return min(hosts, key=lambda h: state.get(f"{h}_composure", 1)) if hosts else None
            if owner in present:
                return owner
            if owner != "any":
                return None
        # any
        if addressee in present:
            return addressee
        if last_speaker in present:
            return last_speaker
        hosts = [h for h in HOSTS if h in present]
        if hosts:
            return hosts[0]
        return "nora" if "nora" in present else None

    def _tier_safe(self, effects: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        """Topic tiers rise one step at a time and never past the phase cap (interaction-design.md §5.4)."""
        cap = self.tier_cap.get(state.get("story_phase", "early"), 3)
        out = {}
        for key, val in effects.items():
            if key.startswith("topic_tier.") and isinstance(val, int):
                cur = int((state.get("topic_tier") or {}).get(key.split(".", 1)[1], 0))
                if val > cap or val > cur + 1 or val <= cur:
                    continue
            out[key] = val
        return out

    # ------------------------------------------------------------------ caps and claims
    def cap_deltas(self, before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
        """Each variable moves at most its per-turn step (interaction-design.md §5.4). Returns the capped state
        and the variables that were clipped, with the delta that was asked for."""
        after = dict(after)
        clipped: dict[str, float] = {}
        for var, cap in self.per_turn_cap.items():
            a, b = before.get(var), after.get(var)
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                continue
            delta = b - a
            if abs(delta) > cap + 1e-9:
                clipped[var] = round(delta, 4)
                capped = a + (cap if delta > 0 else -cap)
                after[var] = int(round(capped)) if isinstance(a, int) and isinstance(b, int) else round(capped, 4)
        return after, clipped

    def recover(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        """A host the turn did not shake gets a little composure back (plan.md R25): pressure has to be kept up,
        not banked. Never above the ceiling, never once the truth is out (`when`)."""
        rec = self.recovery
        if rec is None or not truthy(rec["_when"], {**after, "turn": {}}):
            return after
        after = dict(after)
        for var, ceiling in rec["ceiling"].items():
            a, b = before.get(var), after.get(var)
            if isinstance(a, (int, float)) and a == b and b < ceiling:
                after[var] = round(min(ceiling, b + float(rec["per_turn"])), 4)
        return after

    @staticmethod
    def record_claims(state: dict[str, Any], turn: dict[str, Any], turn_no: int) -> dict[str, Any]:
        """The claims log and who heard each one (interaction-design.md §5.5). Never touches `revealed`."""
        claims = list(turn.get("claims") or [])
        if not claims:
            return state
        state = dict(state)
        present = WorldRules.present(state)
        to = turn.get("addressee") or "self"
        if to not in ("julian", "mia", "both", "nora", "self"):
            to = "self"
        state["claims"] = [*state.get("claims", []), *({"fact": f, "to": to, "turn": turn_no} for f in claims)]
        heard = {k: list(v) for k, v in (state.get("heard_by") or {}).items()}
        listeners = list(present)
        if to == "nora" and "nora" not in listeners:
            listeners.append("nora")  # on the phone
        for f in claims:
            heard[f] = sorted(set(heard.get(f, [])) | set(listeners))
        state["heard_by"] = heard
        return state
