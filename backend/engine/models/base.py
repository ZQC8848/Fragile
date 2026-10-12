"""Three switchable paths per module and shadow mode (backend-design.md §2 principles 2-3, §7.2).

    MODEL_ENCODER / MODEL_GUARD / MODEL_TENSION = rule | llm | trained      (default llm)
    MODEL_SCORER = rule | llm | trained | random, or the scorer letters A | B | C   (default llm = B)
    MODEL_SHADOW = 1   run every path on every call and log all outputs; only the active one decides

`trained` is a placeholder until the students exist: it delegates to `llm` and says so in the output
(`delegated_to`), so the substitution is visible in every log line.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

PATHS = ("rule", "llm", "trained")

#: MODEL_SCORER also accepts the Wrongest Person scorer letters
SCORER_ALIASES = {"a": "rule", "b": "llm", "c": "trained", "random": "random"}


def path_from_env(module: str, default: str = "llm") -> str:
    raw = (os.getenv(f"MODEL_{module.upper()}") or default).strip().lower()
    raw = raw.split("@")[0]  # MODEL_SCORER=trained@v3: the version goes to the registry, later
    if module == "scorer":
        raw = SCORER_ALIASES.get(raw, raw)
        if raw not in (*PATHS, "random"):
            raise ValueError(f"MODEL_SCORER={raw!r}: expected rule|llm|trained|random or A|B|C")
    elif raw not in PATHS:
        raise ValueError(f"MODEL_{module.upper()}={raw!r}: expected rule|llm|trained")
    return raw


def shadow_from_env() -> bool:
    return os.getenv("MODEL_SHADOW", "0").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class SlotRun:
    """One call through a module: the active path's result plus, in shadow mode, every other path's."""

    active: str
    result: Any
    shadow: dict[str, Any] = field(default_factory=dict)

    def log(self, dump=lambda r: r) -> dict[str, Any]:
        return {"active": self.active, "result": dump(self.result), "shadow": {k: dump(v) for k, v in self.shadow.items()}}


async def run_slot(paths: dict[str, Any], active: str, shadow: bool, call, retag) -> SlotRun:
    """Call the active path, and in shadow mode every other one. `trained` placeholders delegate to `llm`,
    so when both run the llm result is reused (`retag(result, "trained")`) instead of paying twice."""
    results: dict[str, Any] = {active: await call(paths[active])}
    if shadow:
        for name, p in paths.items():
            if name in results:
                continue
            if name == "trained" and "llm" in results and getattr(p, "delegates", False):
                results[name] = retag(results["llm"], name)
            else:
                results[name] = await call(p)
    return SlotRun(active, results.pop(active), results)
