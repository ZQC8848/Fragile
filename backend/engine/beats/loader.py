"""Load beat YAML files, validate against schemas/beat.json, compile rule strings to JSON Logic."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from engine.dsl import compile_expr, referenced_vars
from engine.state.schema import SCHEMAS_DIR

# TODO(M3): load schemas/beat_v2.json (written in M1). Wrongest Person's schemas/beat.json was not
# copied, so until then beats are not schema-validated (an empty schema accepts everything).
_BEAT_SCHEMA_PATH = SCHEMAS_DIR / "beat.json"
BEAT_SCHEMA = json.loads(_BEAT_SCHEMA_PATH.read_text(encoding="utf-8")) if _BEAT_SCHEMA_PATH.exists() else {}
_beat_validator = jsonschema.Draft202012Validator(BEAT_SCHEMA)

GENERATE_NEW_ID = "GENERATE_NEW"


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
        return self.raw.get("dramatic_intent", "")

    @property
    def goals(self) -> dict[str, Any]:
        return self.raw.get("beat_goals", {}) or {}

    @property
    def is_ending(self) -> bool:
        return self.type == "ending"

    def text_for_scorer(self) -> str:
        """Content-only description (constraint A: no ids as features)."""
        eff = ", ".join(f"{k} {v}" for k, v in self.effects.items())
        return (
            f"type={self.type}; slope={self.tension_slope:+.0f}; effects=[{eff}]; "
            f"intent: {self.intent.strip()}"
        )

    def public(self) -> dict[str, Any]:
        return {**self.raw, "compiled": self.compiled, "source_path": self.source_path}


class BeatLoadError(ValueError):
    pass


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """PyYAML (YAML 1.1) reads the bare key `on:` as boolean True. Authors and the proposer write
    `on:`, so map it back before validation."""
    goals = raw.get("beat_goals")
    if isinstance(goals, dict) and isinstance(goals.get("mix_in"), list):
        fixed = []
        for m in goals["mix_in"]:
            if isinstance(m, dict) and True in m and "on" not in m:
                m = {("on" if k is True else k): v for k, v in m.items()}
            fixed.append(m)
        goals["mix_in"] = fixed
    return raw


def compile_beat(raw: dict[str, Any], state_vars: set[str] | None = None, source: str | None = None) -> Beat:
    raw = _normalize(raw)
    errs = [e.message for e in _beat_validator.iter_errors(raw)]
    if errs:
        raise BeatLoadError(f"{source or raw.get('id')}: " + "; ".join(errs))
    compiled: dict[str, Any] = {
        "preconditions": compile_expr(raw.get("preconditions")),
        "abort_if": compile_expr(raw.get("abort_if")) if raw.get("abort_if") else False,
        "priority_test": [
            {"when": compile_expr(p["when"]), "add": float(p["add"])} for p in (raw.get("priority_test") or [])
        ],
        "mix_in": [
            {"on": compile_expr(m["on"]), "do": m["do"]} for m in ((raw.get("beat_goals") or {}).get("mix_in") or [])
        ],
    }
    if state_vars is not None:
        used: set[str] = set()
        used |= referenced_vars(compiled["preconditions"])
        used |= referenced_vars(compiled["abort_if"])
        for p in compiled["priority_test"]:
            used |= referenced_vars(p["when"])
        # mix_in rules may read `discourse_act` / `interaction.*` which are event fields, not state
        unknown = {u for u in used if u not in state_vars and u not in ("discourse_act", "interaction", "objects")}
        if unknown:
            raise BeatLoadError(f"{source or raw.get('id')}: rules reference unknown state variables {sorted(unknown)}")
        for var in (raw.get("effects") or {}):
            if var not in state_vars:
                raise BeatLoadError(f"{source or raw.get('id')}: effects target unknown variable {var!r}")
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
            beat = compile_beat(doc, state_vars, source=str(path.relative_to(directory.parent.parent)))
            if beat.id in seen:
                raise BeatLoadError(f"duplicate beat id {beat.id!r} in {path}")
            seen.add(beat.id)
            beats.append(beat)
    return beats
