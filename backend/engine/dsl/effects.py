"""Apply a beat's `effects` to a state document.

Effect forms (docs/backend-design.md section 5):
    "+1" / "-0.1"        increment / decrement a numeric variable (clamped to the schema range)
    "moved"              assign an enum/string value
    3                    assign a number
    ["add", "debt"]      add an item to a set-like list (more items may follow: ["add", "a", "b"])
    ["remove", "debt"]   remove items
Keys may be one level dotted into an object variable: "topic_tier.leo": "+1".
"""

from __future__ import annotations

import re
from typing import Any

_DELTA_RE = re.compile(r"^\s*([+-])\s*(\d+(?:\.\d+)?)\s*$")


def apply_effects(state: dict[str, Any], effects: dict[str, Any], schema_props: dict[str, Any]) -> dict[str, Any]:
    """Return a NEW state dict with effects applied. Unknown variables raise KeyError so a typo in a
    beat file fails at load/test time instead of silently doing nothing."""
    new = dict(state)
    for key, eff in (effects or {}).items():
        var, _, sub = key.partition(".")
        if var not in schema_props:
            raise KeyError(f"effect targets unknown state variable {key!r}")
        prop = schema_props[var]
        target = new
        if sub:
            nested = prop.get("properties") or {}
            if sub not in nested:
                raise KeyError(f"effect targets unknown state variable {key!r}")
            target = new[var] = dict(new.get(var) or {})
            var, prop = sub, nested[sub]
        target[var] = _apply_one(target.get(var), eff, prop, key)
    return new


def _apply_one(cur: Any, eff: Any, prop: dict[str, Any], key: str) -> Any:
    if isinstance(eff, str) and (m := _DELTA_RE.match(eff)):
        sign, amount = m.group(1), float(m.group(2))
        delta = amount if sign == "+" else -amount
        val = (cur or 0) + delta
        if "integer" in _types(prop):
            val = int(round(val))
        return _clamp(val, prop)
    if isinstance(eff, list) and len(eff) >= 2 and eff[0] in ("add", "remove"):
        items = list(cur or [])
        for item in eff[1:]:
            if eff[0] == "add" and item not in items:
                items.append(item)
            if eff[0] == "remove" and item in items:
                items.remove(item)
        return items
    if "enum" in prop and eff not in prop["enum"]:
        raise ValueError(f"effect {key}={eff!r} not in enum {prop['enum']}")
    return _clamp(eff, prop) if isinstance(eff, (int, float)) and not isinstance(eff, bool) else eff


def _types(prop: dict[str, Any]) -> set[str]:
    t = prop.get("type")
    if isinstance(t, list):
        return set(t)
    return {t} if t else set()


def _clamp(val: Any, prop: dict[str, Any]) -> Any:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        lo, hi = prop.get("minimum"), prop.get("maximum")
        if lo is not None:
            val = max(lo, val)
        if hi is not None:
            val = min(hi, val)
        if "integer" in _types(prop):
            val = int(val)
        else:
            val = round(float(val), 4)
    return val
