"""Load beat YAML files, validate against schemas/beat_v2.json, compile rule strings to JSON Logic."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from engine.dsl import compile_expr, referenced_vars, truthy
from engine.paths import SCHEMAS_DIR

BEAT_SCHEMA = json.loads((SCHEMAS_DIR / "beat_v2.json").read_text(encoding="utf-8"))
_beat_validator = jsonschema.Draft202012Validator(BEAT_SCHEMA)

GENERATE_NEW_ID = "GENERATE_NEW"

#: rules may read these besides state variables: the transient per-turn namespace
RULE_NAMESPACES = {"turn"}


@dataclass
class Beat:
    raw: dict[str, Any]
    compiled: dict[str, Any] = field(default_factory=dict)
    source_path: str | None = None

    # -- convenience accessors ---------------------------------------------
    @property
    def id(self) -> str:
        return self.raw["id"]

    @property
    def title(self) -> str:
        return self.raw.get("title", self.raw["id"])

    @property
    def type(self) -> str:
        return self.raw["type"]

    @property
    def origin(self) -> str:
        return self.raw.get("origin", "authored")

    @property
    def weight(self) -> float:
        return float(self.raw.get("weight", 1.0))

    @property
    def tension_slope(self) -> float:
        return float(self.raw.get("tension_slope", 0))

    @property
    def effects(self) -> dict[str, Any]:
        return self.raw.get("effects", {}) or {}

    @property
    def intent(self) -> str:
        return self.raw.get("dramatic_intent", "").strip()

    @property
    def steps(self) -> list[dict[str, Any]]:
        return self.raw["steps"]

    @property
    def minutes(self) -> float | None:
        m = self.raw.get("minutes")
        return float(m) if m is not None else None

    @property
    def max_turns(self) -> int:
        return int(self.raw.get("max_turns", 3))

    @property
    def outcomes(self) -> list[dict[str, Any]]:
        return self.raw.get("outcomes") or []

    @property
    def entries(self) -> list[dict[str, Any]]:
        return self.raw["entries"]

    @property
    def must_follow_rank(self) -> int | None:
        mf = self.raw.get("must_follow")
        return int(mf["rank"]) if mf else None

    @property
    def ending_rank(self) -> int | None:
        r = self.raw.get("ending_rank")
        return int(r) if r is not None else None

    @property
    def is_ending(self) -> bool:
        return self.type == "ending"

    @property
    def tableau(self) -> str | None:
        return self.raw.get("tableau")

    @property
    def epilogue(self) -> str | None:
        return self.raw.get("epilogue")

    def reveals(self) -> set[str]:
        """Facts this beat may put into `revealed` (its own effects, outcomes and mix-ins). The narrator may
        speak of them while the beat runs, before the end-of-beat effects land."""
        out: set[str] = set()
        for eff in [self.effects, *(o.get("effects") for o in self.outcomes), *(m.get("effects") for m in self.raw.get("mix_in") or [])]:
            rev = (eff or {}).get("revealed")
            if isinstance(rev, list) and rev and rev[0] == "add":
                out |= set(rev[1:])
        return out

    def resolve(self, steps: list[dict[str, Any]], ctx: dict[str, Any]) -> list[dict[str, Any]]:
        """The steps as the narrator gets them: each step's `do` plus every conditional line that holds now
        (plan.md R26). The engine decides the branch; the narrator never sees a condition."""
        out = []
        for st in steps:
            rules = self.compiled["lines"].get(st["id"])
            st = {k: v for k, v in st.items() if k != "lines"}
            if rules:
                extra = [ln["do"] for ln, r in zip(self.raw_step(st["id"])["lines"], rules, strict=True) if truthy(r, ctx)]
                st["do"] = " ".join([st["do"], *extra])
            out.append(st)
        return out

    def raw_step(self, step_id: str) -> dict[str, Any]:
        return next(s for s in self.steps if s["id"] == step_id)

    def text_for_scorer(self) -> str:
        """Content-only description: scorers never see the id (backend-design.md §4.1)."""
        eff = ", ".join(f"{k} {v}" for k, v in self.effects.items() if k not in ("player_room", "julian_room", "mia_room"))
        steps = " | ".join(s["do"] for s in self.steps)
        minutes = f"{self.minutes:g}" if self.minutes is not None else "default"
        return (
            f"type={self.type}; slope={self.tension_slope:+.0f}; minutes={minutes}; effects=[{eff}]; "
            f"intent: {self.intent} steps: {steps}"
        )

    def public(self) -> dict[str, Any]:
        return {**self.raw, "source_path": self.source_path}


class BeatLoadError(ValueError):
    pass


def _rule_vars(nodes: list[Any]) -> set[str]:
    used: set[str] = set()
    for n in nodes:
        used |= referenced_vars(n)
    return used


def compile_beat(raw: dict[str, Any], state_vars: set[str] | None = None, source: str | None = None) -> Beat:
    errs = [f"{list(e.absolute_path)}: {e.message}" for e in _beat_validator.iter_errors(raw)]
    if errs:
        raise BeatLoadError(f"{source or raw.get('id')}: " + "; ".join(errs))

    def rule(src: str | None, default: Any = True) -> Any:
        return compile_expr(src) if src else default

    try:
        compiled: dict[str, Any] = {
            "preconditions": rule(raw["preconditions"]),
            "abort_if": rule(raw.get("abort_if"), False),
            "priority_test": [{"when": rule(p["when"]), "add": float(p["add"])} for p in raw.get("priority_test") or []],
            "entries": [rule(e.get("when")) for e in raw["entries"]],
            "must_follow": rule(raw["must_follow"]["when"]) if raw.get("must_follow") else False,
            "mix_in": [rule(m["when"]) for m in raw.get("mix_in") or []],
            "outcomes": [rule(o.get("when"), None) for o in raw.get("outcomes") or []],
            "lines": {st["id"]: [rule(ln["when"]) for ln in st["lines"]] for st in raw.get("steps") or [] if st.get("lines")},
        }
    except ValueError as e:
        raise BeatLoadError(f"{source or raw.get('id')}: {e}") from e
    if state_vars is not None:
        nodes = [compiled["preconditions"], compiled["abort_if"], compiled["must_follow"], *compiled["entries"], *compiled["mix_in"]]
        nodes += [p["when"] for p in compiled["priority_test"]] + [o for o in compiled["outcomes"] if o is not None]
        nodes += [r for rules in compiled["lines"].values() for r in rules]
        unknown = _rule_vars(nodes) - state_vars - RULE_NAMESPACES
        if unknown:
            raise BeatLoadError(f"{source or raw.get('id')}: rules reference unknown state variables {sorted(unknown)}")
        effects = [raw.get("effects"), *(o.get("effects") for o in raw.get("outcomes") or []), *(m.get("effects") for m in raw.get("mix_in") or [])]
        for eff in effects:
            for key in eff or {}:
                if key.split(".")[0] not in state_vars:
                    raise BeatLoadError(f"{source or raw.get('id')}: effects target unknown variable {key!r}")
    return Beat(raw=raw, compiled=compiled, source_path=source)


def load_beats(directory: Path, state_vars: set[str] | None = None) -> list[Beat]:
    beats: list[Beat] = []
    seen: set[str] = set()
    for path in sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not raw:
            continue
        docs = raw if isinstance(raw, list) else [raw]
        for doc in docs:
            beat = compile_beat(doc, state_vars, source=f"{directory.name}/{path.name}")
            if beat.id in seen:
                raise BeatLoadError(f"duplicate beat id {beat.id!r} in {path}")
            seen.add(beat.id)
            beats.append(beat)
    return beats
