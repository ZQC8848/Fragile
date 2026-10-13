"""GENERATE_NEW: author new beats on the spot (backend-design.md §3.1, interaction-design.md §7.1).

    proposer LLM -> 1..3 beat drafts in beat v2 format
    hard checks (no LLM): schema, DSL compiles against state_v2, preconditions and an entry hold now,
                          `minutes` within [0.5, 2] x the phase default, no `revealed` anywhere, no
                          must-follow, no endings, intent not a repeat of a played beat
    the active scorer (M1) ranks the survivors (the drama manager does this; judge stays offline)

Drafts that pass are written to data/candidate_pool/ for human review. Convergence: after two generated beats
in a row GENERATE_NEW leaves the candidate list (engine/dm), and the clock's pending events take over.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import yaml

from engine.beats import Beat, BeatLoadError, BeatPool, compile_beat, completed, rule_ctx
from engine.clock import StoryClock
from engine.dsl import truthy
from engine.llm import LLMOutputError, extract_json, get_client
from engine.models.prompts import BUILTIN_V0, system_prompt
from engine.paths import DATA_DIR
from engine.state.schema import StateSchema

CANDIDATE_POOL_DIR = DATA_DIR / "candidate_pool"

_PROPOSER_SYSTEM = """You are the writers' room of a turn-based interactive drama. The drama manager found no shelf beat
that fits the moment, so author 1 to 3 NEW short beats that follow from the current state and the player's last
input. Return ONLY JSON: {"beats": [<beat>, ...]} where each beat has the beat v2 shape:
{"id": "snake_case", "title": "...", "type": "satellite", "origin": "generated", "schema_version": 2,
 "preconditions": "<DSL over STATE_VARS that is true now>",
 "entries": [{"id": "default", "opening": "<what the narrator stages first>"}],
 "tension_slope": -2..2, "effects": {"tension": "<slope x 0.5, e.g. +0.5>"}, "minutes": <MINUTES_RANGE>,
 "max_turns": 2, "dramatic_intent": "<2-3 sentences>",
 "steps": [{"id": "snake_case", "do": "<a story action the narrator must deliver>"}, ...2 to 3 steps]}
HARD RULES: never touch `revealed`; never introduce new facts about Leo, the money or the afternoon; no endings;
no must_follow; characters stay in the rooms they are in."""
BUILTIN_V0.setdefault("proposer", _PROPOSER_SYSTEM)


@dataclass
class ProposerResult:
    accepted: list[Beat] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    saved: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {"accepted": [b.id for b in self.accepted], "rejected": self.rejected, "meta": self.meta, "saved": self.saved}


class Proposer:
    def __init__(self, schema: StateSchema, clock: StoryClock, temperature: float = 0.9, save: bool = True):
        self.schema = schema
        self.clock = clock
        self.save = save
        self.client = get_client("proposer", temperature, mock_handler=_mock_proposer)
        self._n = 0

    async def generate(
        self,
        *,
        pool: BeatPool,
        state: dict[str, Any],
        turn: dict[str, Any],
        state_text: str,
        recent_dialogue: list[str],
        last_input: dict[str, Any] | None,
    ) -> ProposerResult:
        story_min = float(state.get("story_min", 0))
        d = self.clock.default_minutes(story_min)
        lo, hi = self.clock.generated_range
        played = [h["beat_id"] for h in state.get("beat_history", []) if h.get("completed", True)]
        req = {
            "STATE": state_text,
            "STATE_VARS": sorted(v for v in self.schema.props if v not in ("schema_version", "beat_history", "heard_by", "claims")),
            "ROOMS": {"player": state.get("player_room"), "julian": state.get("julian_room"), "mia": state.get("mia_room"), "nora": state.get("nora_room")},
            "MINUTES_RANGE": [round(lo * d, 2), round(hi * d, 2)],
            "PHASE_DEFAULT_MINUTES": d,
            "recent_dialogue": recent_dialogue[-8:],
            "last_player_input": last_input,
            "already_played": played,
            "n": self._n,
        }
        self._n += 1
        out = ProposerResult()
        try:
            prompt = system_prompt("proposer")
            res = await self.client.call_json(prompt.text, json.dumps(req, ensure_ascii=False), prompt_version=prompt.version)
        except LLMOutputError as e:
            out.meta = e.result.meta()
            return out
        out.meta = res.meta()
        drafts = res.data.get("beats", []) if isinstance(res.data, dict) else []
        for draft in drafts[:3]:
            beat, problems = self.hard_check(draft, pool, state, turn)
            if beat is None:
                out.rejected.append({"id": (draft or {}).get("id") if isinstance(draft, dict) else None, "problems": problems})
                continue
            out.accepted.append(beat)
            if self.save:
                out.saved.append(self._save(beat))
        return out

    def hard_check(self, draft: Any, pool: BeatPool, state: dict[str, Any], turn: dict[str, Any]) -> tuple[Beat | None, list[str]]:
        if not isinstance(draft, dict):
            return None, ["draft is not an object"]
        draft = {**draft, "origin": "generated", "schema_version": 2}
        base = re.sub(r"[^a-z0-9_]", "_", str(draft.get("id") or "generated").lower()).strip("_") or "generated"
        if not base[0].isalpha():
            base = f"gen_{base}"
        bid, k = base, 2
        while bid in pool.by_id:
            bid, k = f"{base}_{k}", k + 1
        draft["id"] = bid
        problems: list[str] = []
        if draft.get("type") != "satellite" and draft.get("type") != "spine":
            problems.append("only satellite or spine beats may be generated")
        if "must_follow" in draft or "ending_rank" in draft:
            problems.append("generated beats may not be must-follow or endings")
        if "revealed" in json.dumps({k: draft.get(k) for k in ("effects", "outcomes", "mix_in")}):
            problems.append("generated beats may not touch revealed")
        if problems:
            return None, problems
        try:
            beat = compile_beat(draft, set(self.schema.props), source="generated")
        except (BeatLoadError, ValueError) as e:
            return None, [str(e)]
        ctx = rule_ctx(state, turn)
        if not truthy(beat.compiled["preconditions"], ctx) or pool.entry_for(beat, ctx) is None:
            problems.append("preconditions or entries do not hold now")
        if beat.minutes is None or not self.clock.minutes_in_range(beat.minutes, float(state.get("story_min", 0))):
            problems.append(f"minutes {beat.minutes} outside the allowed range")
        if any(completed(state, b.id) and b.intent.strip() == beat.intent.strip() for b in pool.beats):
            problems.append("intent repeats a played beat")
        return (None, problems) if problems else (beat, [])

    @staticmethod
    def _save(beat: Beat) -> str:
        CANDIDATE_POOL_DIR.mkdir(parents=True, exist_ok=True)
        path = CANDIDATE_POOL_DIR / f"{int(time.time())}_{beat.id}.yaml"
        raw = {**beat.raw, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return str(path.name)


def _mock_proposer(system: str, user: str) -> dict[str, Any]:
    """One quiet, harmless beat: the hosts keep up appearances. Valid in any room the player shares with a host."""
    req = extract_json(user)
    minutes = req["PHASE_DEFAULT_MINUTES"]
    n = req.get("n", 0)
    return {
        "beats": [
            {
                "id": f"gen_keeping_up_{n}",
                "title": "Keeping up appearances",
                "type": "satellite",
                "preconditions": "julian_room == player_room or mia_room == player_room",
                "entries": [{"id": "default", "opening": "Someone refills a glass that was not empty."}],
                "tension_slope": 0,
                "effects": {},
                "minutes": minutes,
                "max_turns": 2,
                "dramatic_intent": "A lull. The hosts fill the silence with small talk about the move, a little too brightly.",
                "steps": [
                    {"id": "small_talk", "do": "Small talk about the flight and the weather in the new city."},
                    {"id": "the_lull", "do": "The talk runs out. Everyone looks at their glass."},
                ],
            }
        ]
    }
