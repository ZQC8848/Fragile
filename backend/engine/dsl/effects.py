"""Apply a beat's `effects` to a state document.

Effect forms (docs/backend-design.md section 5):
    "+1" / "-0.1"        increment / decrement a numeric variable (clamped to the schema range)
    "moved"              assign an enum/string value
    3                    assign a number
    ["add", "debt"]      add an item to a set-like list
    ["remove", "debt"]   remove an item
"""

from __future__ import annotations

import re
from typing import Any

_DELTA_RE = re.compile(r"^\s*([+-])\s*(\d+(?:\.\d+)?)\s*$")


def apply_effects(state: dict[str, Any], effects: dict[str, Any], schema_props: dict[str, Any]) -> dict[str, Any]:
    """Return a NEW state dict with effects applied. Unknown variables raise KeyError so a typo in a
    beat file fails at load/test time instead of silently doing nothing."""
    new = dict(state)
    for var, eff in (effects or {}).items():
        if var not in schema_props:
            raise KeyError(f"effect targets unknown state variable {var!r}")
        prop = schema_props[var]
        cur = new.get(var)
        if isinstance(eff, str) and (m := _DELTA_RE.match(eff)):
            sign, amount = m.group(1), float(m.group(2))
            delta = amount if sign == "+" else -amount
            val = (cur or 0) + delta
            if "integer" in _types(prop):
                val = int(round(val))
            new[var] = _clamp(val, prop)
        elif isinstance(eff, list) and len(eff) == 2 and eff[0] in ("add", "remove"):
            items = list(cur or [])
            if eff[0] == "add" and eff[1] not in items:
                items.append(eff[1])
            if eff[0] == "remove" and eff[1] in items:
                items.remove(eff[1])
            new[var] = items
        else:
            if "enum" in prop and eff not in prop["enum"]:
                raise ValueError(f"effect {var}={eff!r} not in enum {prop['enum']}")
            new[var] = _clamp(eff, prop) if isinstance(eff, (int, float)) and not isinstance(eff, bool) else eff
    return new


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
