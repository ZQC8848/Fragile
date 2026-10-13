"""Knowledge cards and the per-turn knowledge slice (interaction-design.md §9.3, data/knowledge/*.yaml).

Each turn the narrator only gets what may be said now: for every character in the scene, their persona and
the facts whose `may_say_when` holds. Secrets it never receives it cannot leak; the guard is the second line.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from engine.dsl import compile_expr, truthy
from engine.paths import DATA_DIR

CHARACTERS = ("julian", "mia", "nora", "player")


class Knowledge:
    def __init__(self, cards: dict[str, dict[str, Any]]):
        self.cards = cards
        self._rules = {
            (who, f["id"]): compile_expr(f["may_say_when"]) if f.get("may_say_when") else False
            for who, card in cards.items()
            for f in card["facts"]
        }

    @classmethod
    def from_dir(cls, directory: Path | None = None) -> Knowledge:
        directory = directory or DATA_DIR / "knowledge"
        cards = {}
        for who in CHARACTERS:
            path = directory / f"{who}.yaml"
            if path.exists():
                cards[who] = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(cards)

    def sayable(self, who: str, state: dict[str, Any]) -> list[dict[str, Any]]:
        card = self.cards.get(who)
        if not card:
            return []
        ctx = {**state, "turn": {}}
        out = []
        for f in card["facts"]:
            if f.get("knows") is False:
                continue
            rule = self._rules[(who, f["id"])]
            if rule is not False and truthy(rule, ctx):
                out.append(f)
        return out

    def allowed_facts(self, who: str, state: dict[str, Any]) -> set[str]:
        """State `revealed` ids this character may speak of now."""
        return {f["fact"] for f in self.sayable(who, state) if f.get("fact")}

    def player_card(self, state: dict[str, Any]) -> dict[str, Any]:
        """What the player is told walking in (plan.md R24): who they are, and every fact they may state now."""
        player = self.cards.get("player") or {}
        return {
            "identity": (player.get("persona") or {}).get("identity", ""),
            "knows": [f["text"] for f in self.sayable("player", state)],
        }

    def slice(self, state: dict[str, Any], speakers: list[str], perceivable: list[str]) -> dict[str, Any]:
        """What the narrator may use this turn."""
        out: dict[str, Any] = {}
        for who in speakers:
            card = self.cards.get(who)
            if not card:
                continue
            persona = card.get("persona") or {}
            out[who] = {
                "persona": {k: persona.get(k) for k in ("surface", "wants", "voice", "never_says", "tells", "background") if persona.get(k)},
                "may_say": [f["text"] for f in self.sayable(who, state)],
            }
        player = self.cards.get("player") or {}
        out["player"] = {
            "knows": [f["text"] for f in self.sayable("player", state)],
            "revealed": list(state.get("revealed", [])),
            "can_see": perceivable,
            "rule": (player.get("persona") or {}).get("rule"),
        }
        return out
