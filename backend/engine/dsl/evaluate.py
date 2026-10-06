"""Minimal JSON Logic evaluator with the project's custom ops.

Supported: var, and, or, !, ==, !=, <, <=, >, >=, in, +, -, if
Custom:    near(a, b)        two actors/objects in the same zone (see DEFAULT_OBJECT_ZONES)
           played(id)        beat id is in beat_history
           has(list, item)   membership, same as `item in list`
           count(list) / len(x)
           min / max / abs

The frontend uses json-logic-js for the standard ops; custom ops are registered there with
the same semantics (frontend/src/protocol/logic.ts).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

JsonLogic = Any


class EvalError(ValueError):
    pass


def _var(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in str(path).split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return default
    return cur


def _zone_of(data: Mapping[str, Any], name: str) -> str | None:
    """Zone of an actor (may/lin/guest via *_zone) or an object (objects.<name>.zone or <name>_zone)."""
    if name in ("may", "lin", "guest"):
        return _var(data, f"{name}_zone")
    z = _var(data, f"objects.{name}.zone")
    if z is None:
        z = _var(data, f"{name}_zone")
    if z is None:
        z = DEFAULT_OBJECT_ZONES.get(name)
    return z


# Where the planted objects live unless the state says otherwise. Kept here rather than in
# state so the DSL can say near(may, poisoned_glass) without the state carrying geometry.
DEFAULT_OBJECT_ZONES: dict[str, str] = {
    "poisoned_glass": "guest_table",
    "maotai_bottle": "guest_table",
    "envelope": "guest_table",
    "gun": "guest_table",
    "front_door": "entrance",
    "kitchen_door": "kitchen_door",
    "bentley": "street",
    "bar": "bar",
    "counter": "counter",
}


def evaluate(node: JsonLogic, data: Mapping[str, Any]) -> Any:
    if not isinstance(node, dict):
        if isinstance(node, list):
            return [evaluate(n, data) for n in node]
        return node
    if len(node) != 1:
        raise EvalError(f"malformed JSON Logic node: {node!r}")
    op, raw_args = next(iter(node.items()))
    if op == "var":
        return _var(data, raw_args if isinstance(raw_args, str) else raw_args[0])
    if op == "and":
        result: Any = True
        for a in raw_args:
            result = evaluate(a, data)
            if not result:
                return result
        return result
    if op == "or":
        result = False
        for a in raw_args:
            result = evaluate(a, data)
            if result:
                return result
        return result
    if op == "if":
        # if [cond, then, cond2, then2, ..., else]
        i = 0
        while i + 1 < len(raw_args):
            if evaluate(raw_args[i], data):
                return evaluate(raw_args[i + 1], data)
            i += 2
        return evaluate(raw_args[i], data) if i < len(raw_args) else None

    if op == "near":
        # arguments are NAMES (may, lin, poisoned_glass), written bare in the DSL and therefore parsed as vars
        names = [a["var"] if isinstance(a, dict) and "var" in a else a for a in raw_args]
        a = _zone_of(data, str(names[0]))
        b = _zone_of(data, str(names[1]))
        return a is not None and a == b

    args = [evaluate(a, data) for a in (raw_args if isinstance(raw_args, list) else [raw_args])]

    if op == "!":
        return not args[0]
    if op == "==":
        return args[0] == args[1]
    if op == "!=":
        return args[0] != args[1]
    if op in ("<", "<=", ">", ">="):
        a, b = args[0], args[1]
        if a is None or b is None:
            return False
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
    if op == "in":
        needle, hay = args[0], args[1]
        if hay is None:
            return False
        return needle in hay
    if op == "has":
        hay, needle = args[0], args[1]
        return bool(hay) and needle in hay
    if op == "+":
        return sum(x or 0 for x in args)
    if op == "-":
        if len(args) == 1:
            return -args[0]
        return (args[0] or 0) - (args[1] or 0)
    if op in ("count", "len"):
        return len(args[0] or [])
    if op == "min":
        return min(args)
    if op == "max":
        return max(args)
    if op == "abs":
        return abs(args[0])
    if op == "played":
        wanted = str(args[0])
        return any((h.get("beat_id") if isinstance(h, dict) else h) == wanted for h in (data.get("beat_history") or []))
    raise EvalError(f"unknown op {op!r}")


def truthy(node: JsonLogic, data: Mapping[str, Any]) -> bool:
    return bool(evaluate(node, data))


def explain(node: JsonLogic, data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten a top-level `and` into per-clause results for the Console."""
    clauses = node["and"] if isinstance(node, dict) and "and" in node else [node]
    out = []
    for c in clauses:
        try:
            val = bool(evaluate(c, data))
        except EvalError:
            val = False
        out.append({"clause": c, "value": val})
    return out
