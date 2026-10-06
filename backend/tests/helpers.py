"""Shared helpers for the contract and content tests: schema loading, default state, rule and effect
checks against schemas/state_v2.json."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from engine.dsl import apply_effects, compile_expr, referenced_vars

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
SCHEMAS = REPO / "schemas"
DATA = BACKEND / "data"
FIXTURES = Path(__file__).parent / "fixtures"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def errors(schema: dict[str, Any], doc: Any) -> list[str]:
    return [f"{list(e.absolute_path)}: {e.message}" for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)]


STATE = load_json(SCHEMAS / "state_v2.json")
STATE_PROPS: dict[str, Any] = STATE["properties"]
FACTS = set(STATE["$defs"]["Fact"]["enum"])
ROOMS = set(STATE["$defs"]["Room"]["enum"])
TURN_FIELDS = set(STATE["$defs"]["Turn"]["properties"])


def default_state(**patch: Any) -> dict[str, Any]:
    s = {name: deepcopy(prop["default"]) for name, prop in STATE_PROPS.items()}
    s.update(patch)
    return s


def _vars(node: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "var":
                out.add(str(v if not isinstance(v, list) else v[0]))
            else:
                out |= _vars(v)
    elif isinstance(node, list):
        for v in node:
            out |= _vars(v)
    return out


def check_rule(src: str, where: str) -> None:
    """The rule compiles and reads only state variables, nested state fields or turn.<field>."""
    node = compile_expr(src)
    unknown = referenced_vars(node) - set(STATE_PROPS) - {"turn"}
    assert not unknown, f"{where}: rule {src!r} reads unknown variables {sorted(unknown)}"
    for path in _vars(node):
        head, _, tail = path.partition(".")
        if not tail:
            continue
        first = tail.split(".")[0]
        if head == "turn":
            assert first in TURN_FIELDS, f"{where}: rule {src!r} reads unknown turn field {path!r}"
            continue
        prop = STATE_PROPS[head]
        if "properties" in prop:
            assert first in prop["properties"], f"{where}: rule {src!r} reads unknown nested variable {path!r}"


def check_effects(effects: dict[str, Any] | None, where: str) -> dict[str, Any]:
    """Apply effects to the default state with the engine and validate the result."""
    state = apply_effects(default_state(), effects or {}, STATE_PROPS)
    errs = errors(STATE, state)
    assert not errs, f"{where}: effects {effects} produce an invalid state: {errs}"
    return state
