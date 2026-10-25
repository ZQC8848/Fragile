"""Export the label sets and the action table from the engine into common/*.json.

The training side runs on CARC under a different Python and never imports the engine, so everything it
needs to know about labels lives in these two files. Re-run after schemas/llm/review.json or
data/interactions.yaml changes:

    uv run python -m ml.task2.gen.export_meta
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from engine.paths import DATA_DIR, SCHEMAS_DIR

COMMON = Path(__file__).resolve().parents[1] / "common"


def _enum(node: dict) -> list:
    """The enum of a schema node, looking through anyOf and dropping null."""
    if "enum" in node:
        return [v for v in node["enum"] if v is not None]
    for alt in node.get("anyOf", []):
        if "enum" in alt:
            return [v for v in alt["enum"] if v is not None]
    raise KeyError("no enum in node")


def labels() -> dict:
    review = json.loads((SCHEMAS_DIR / "llm" / "review.json").read_text(encoding="utf-8"))
    props = review["properties"]
    unit = props["units"]["items"]["properties"]
    action = next(a for a in unit["action"]["anyOf"] if a.get("type") == "object")
    return {
        "source": "schemas/llm/review.json",
        "acts": _enum(unit["act"]),
        "addressees": _enum(unit["addressee"]),
        "topics": _enum(unit["topics"]["items"]),
        "verbs": _enum(action["properties"]["verb"]),
        "channels": _enum(unit["channel"]),
        "claims": _enum(props["claims"]["items"]),
        "validity": _enum(props["validity"]["properties"]["label"]),
        "nora_answer": _enum(props["nora_answer"]),
        "side_answer": _enum(props["side_answer"]),
    }


def action_table() -> dict:
    """verb -> allowed targets, and target -> rooms it exists in (null = any room)."""
    raw = yaml.safe_load((DATA_DIR / "interactions.yaml").read_text(encoding="utf-8"))
    rooms = list(raw["rooms"])
    verb_targets: dict[str, set[str]] = {}
    target_rooms: dict[str, list[str] | None] = {}
    for verb, spec in raw["movement"].items():
        targets = [t for t in spec if not t.startswith("_")] if isinstance(spec, dict) else []
        if verb == "go_to":
            targets = rooms
        verb_targets.setdefault(verb, set()).update(targets)
        for t in targets:
            target_rooms.setdefault(t, None)
    for name, obj in raw["objects"].items():
        target_rooms[name] = obj.get("where")
        for verb in obj.get("actions") or {}:
            verb_targets.setdefault(verb, set()).add(name)
    return {
        "source": "data/interactions.yaml",
        "rooms": rooms,
        "verb_targets": {v: sorted(ts) for v, ts in sorted(verb_targets.items())},
        "target_rooms": dict(sorted(target_rooms.items())),
    }


def main() -> None:
    for name, data in (("labels.json", labels()), ("action_table.json", action_table())):
        path = COMMON / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(COMMON.parents[2])}")


if __name__ == "__main__":
    main()
