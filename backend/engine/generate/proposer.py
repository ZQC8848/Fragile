"""Generate a new beat when GENERATE_NEW wins (docs/backend-design.md section 8).

    proposer LLM -> 1..3 beat drafts (author-layer DSL strings)
    hard checks (no LLM): schema, DSL compiles, preconditions true now, effects in range,
                          revealed untouched, intent not a repeat
    judge LLM -> pick the best
    convergence rule: after two consecutive generated beats the third MUST be an ending

Drafts that pass are written to data/candidate_pool/ for later human review in /author.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import yaml

from engine.beats import Beat, BeatLoadError, BeatPool, compile_beat
from engine.dsl import truthy
from engine.llm import get_client
from engine.state.schema import REPO_ROOT, StateSchema

CANDIDATE_POOL_DIR = REPO_ROOT / "backend" / "data" / "candidate_pool"


def bible() -> str:
    # TODO(M3): engine/performer (Wrongest Person's character bible) was not copied. The proposer
    # prompt gets Fragile's characters from the knowledge cards (data/knowledge/) when it is rewritten.
    return ""

_PROPOSER_SYSTEM = (
    "You are the writers' room of an interactive drama. The drama manager found no shelf beat that fits the moment,\n"
    "so you must author 1 to 3 NEW beats (self-contained mini-scenes, 30-60 seconds) that follow naturally from the\n"
    "current state and the player's last input, and that can be performed by the characters.\n\n"
    + bible()
    + "\n\nBEAT FORMAT (return ONLY JSON: {\"beats\": [ ... ]}). Each beat:\n"
    "{\n"
    '  "id": "snake_case_unique", "title": "...", "type": "satellite"|"spine"|"ending",\n'
    '  "preconditions": "<rule string using the state variables listed in STATE_VARS, e.g. \\"may_zone == \'bar\' and glass != \'drunk\'\\">",\n'
    '  "weight": 1.0, "effects": {"tension": "+1", "may_suspicion": "+1", "glass": "moved"},\n'
    '  "tension_slope": -2..2,\n'
    '  "abort_if": "<rule string or empty>",\n'
    '  "dramatic_intent": "<2-4 sentences: what this beat is for, what it reveals or withholds>",\n'
    '  "staging": {"lin": {"move_to": <zone>, "face": "may"}},\n'
    '  "beat_goals": {"transition_in": "...", "body": "...", "mix_in": [{"on": "discourse_act == \'ask_about_guest\'", "do": "..."}],\n'
    '                 "wait": {"timeout_s": 20}, "transition_out": "..."},\n'
    '  "reaction_shots_allowed": 0|1,\n'
    '  "closest_authored_ending": "E1"|"E2"|"E3"|"E4"   (only when type == "ending")\n'
    "}\n"
    "HARD RULES: never put `revealed` in effects. Preconditions MUST be true in the given STATE. Do not repeat a beat\n"
    "already played. If the request says MUST_BE_ENDING, every beat has type \"ending\" and closes the story."
)

_JUDGE_SYSTEM = (
    "You are a dramaturg judging candidate beats for coherence and dramatic value. Return ONLY JSON:\n"
    '{"scores": [{"id": "<beat id>", "score": 0..10, "reason": "<one sentence>"}]}\n'
    "Score high when: follows from the state and the player's last input; keeps characters consistent; advances or\n"
    "productively withholds the central question (can Lin get May out before the guest arrives); performable in\n"
    "under a minute. Score low when: contradicts revealed facts, dumps exposition, changes tone arbitrarily."
)


@dataclass
class GeneratedBeat:
    beat: Beat
    judge_score: float
    judge_reason: str
    saved_path: str | None


class Proposer:
    def __init__(self, schema: StateSchema, temperature: float = 0.9):
        self.schema = schema
        self.client = get_client("proposer", temperature, mock_handler=_mock_proposer, max_tokens=2200)
        self.judge = get_client("judge", 0.0, mock_handler=_mock_judge)

    async def generate(
        self,
        *,
        pool: BeatPool,
        state: dict[str, Any],
        state_text: str,
        recent_dialogue: list[str],
        last_input: dict[str, Any] | None,
        must_be_ending: bool,
        logger=None,
    ) -> GeneratedBeat | None:
        played = [h["beat_id"] for h in state.get("beat_history", [])]
        eligible_titles = [f"{b.id}: {b.intent.strip()[:80]}" for b in pool.eligible(state)]
        req = {
            "STATE": state_text,
            "STATE_VARS": sorted(v for v in self.schema.props if v not in ("schema_version", "beat_history")),
            "ZONES": ["street", "entrance", "guest_table", "bar", "counter", "kitchen_door", "back_corner"],
            "recent_dialogue": recent_dialogue[-8:],
            "last_player_input": last_input,
            "already_played": played,
            "shelf_beats_that_did_not_fit": eligible_titles,
            "MUST_BE_ENDING": must_be_ending,
        }
        data = await self.client.complete_json(_PROPOSER_SYSTEM, json.dumps(req, ensure_ascii=False))
        drafts = data.get("beats", []) if isinstance(data, dict) else []
        if logger:
            logger.event("proposer_output", {"drafts": drafts, "must_be_ending": must_be_ending})

        checked: list[tuple[Beat, list[str]]] = []
        for d in drafts:
            beat, problems = self.hard_check(d, pool, state, played, must_be_ending)
            if beat is not None and not problems:
                checked.append((beat, []))
            elif logger:
                logger.event("proposer_rejected", {"draft": d, "problems": problems})
        if not checked:
            return None

        # judge
        listing = [{"id": b.id, "title": b.title, "intent": b.intent, "effects": b.effects} for b, _ in checked]
        try:
            jd = await self.judge.complete_json(
                _JUDGE_SYSTEM, json.dumps({"STATE": state_text, "last_player_input": last_input, "candidates": listing})
            )
            scores = {s["id"]: s for s in jd.get("scores", []) if "id" in s}
        except Exception:  # noqa: BLE001
            scores = {}
        best, best_score, best_reason = None, -1.0, ""
        for b, _ in checked:
            s = float(scores.get(b.id, {}).get("score", 5))
            if s > best_score:
                best, best_score, best_reason = b, s, str(scores.get(b.id, {}).get("reason", ""))
        assert best is not None
        path = self._save(best)
        return GeneratedBeat(best, best_score, best_reason, path)

    def hard_check(
        self, draft: dict[str, Any], pool: BeatPool, state: dict[str, Any], played: list[str], must_be_ending: bool
    ) -> tuple[Beat | None, list[str]]:
        problems: list[str] = []
        d = dict(draft)
        d.setdefault("origin", "generated")
        d.setdefault("type", "satellite")
        d.setdefault("weight", 1.0)
        d.setdefault("schema_version", self.schema.version)
        d["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        d["id"] = _slug(d.get("id") or d.get("title") or "generated")
        if d["id"] in pool.by_id or d["id"] in played:
            d["id"] = f"{d['id']}_{int(time.time()) % 100000}"
        if "revealed" in (d.get("effects") or {}):
            problems.append("effects modify `revealed`")
        if must_be_ending and d.get("type") != "ending":
            problems.append("must be an ending beat")
        if d.get("type") == "ending" and not d.get("closest_authored_ending"):
            d["closest_authored_ending"] = "E3"
        try:
            beat = compile_beat(d, set(self.schema.props), source="generated")
        except BeatLoadError as e:
            return None, problems + [str(e)]
        if not truthy(beat.compiled["preconditions"], state):
            problems.append("preconditions false in current state")
        for existing in pool.beats:
            if existing.id in played and _similar(existing.intent, beat.intent):
                problems.append(f"intent repeats played beat {existing.id}")
                break
        return beat, problems

    @staticmethod
    def _save(beat: Beat) -> str | None:
        try:
            CANDIDATE_POOL_DIR.mkdir(parents=True, exist_ok=True)
            path = CANDIDATE_POOL_DIR / f"{beat.id}.yaml"
            path.write_text(yaml.safe_dump(beat.raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
            return str(path.relative_to(REPO_ROOT))
        except OSError:
            return None


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_")
    if not s or not s[0].isalpha():
        s = "gen_" + s
    return s[:48]


def _similar(a: str, b: str) -> bool:
    wa = set(re.findall(r"[a-z]{4,}", a.lower()))
    wb = set(re.findall(r"[a-z]{4,}", b.lower()))
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) > 0.6


# ---------------------------------------------------------------------------
def _mock_proposer(system: str, user: str) -> dict[str, Any]:
    req = json.loads(user)
    if req.get("MUST_BE_ENDING"):
        return {
            "beats": [
                {
                    "id": "gen_ending_quiet_exit",
                    "title": "The Quiet Exit",
                    "type": "ending",
                    "preconditions": "true",
                    "effects": {"tension": "-1", "door": "open"},
                    "tension_slope": -1,
                    "dramatic_intent": "Lin gets May out the back a heartbeat before the front door opens. Nothing is said. The story closes on the door.",
                    "beat_goals": {"transition_in": "Lin takes May by the shoulders.", "body": "Lin pushes May toward the kitchen door.", "transition_out": "The front door handle turns."},
                    "closest_authored_ending": "E4",
                }
            ]
        }
    return {
        "beats": [
            {
                "id": "gen_lin_asks_about_the_cello",
                "title": "The Cello Case",
                "type": "satellite",
                "preconditions": "may_zone != 'street'",
                "effects": {"tension": "+0", "may_trust_lin": "+1"},
                "tension_slope": 0,
                "dramatic_intent": "Lin, stalling, asks about the cello case. May says she took the only thing that was hers. A moment of warmth Lin cannot afford.",
                "staging": {"lin": {"face": "may"}},
                "beat_goals": {
                    "transition_in": "Lin: 'You brought that thing through the rain?'",
                    "body": "May explains; Lin almost smiles, then checks the window.",
                    "mix_in": [{"on": "discourse_act == 'ask_about_guest'", "do": "Lin deflects: 'A supplier.'"}],
                    "wait": {"timeout_s": 15},
                    "transition_out": "Lin looks at the door.",
                },
                "reaction_shots_allowed": 0,
            }
        ]
    }


def _mock_judge(system: str, user: str) -> dict[str, Any]:
    req = json.loads(user)
    return {"scores": [{"id": c["id"], "score": 7, "reason": "mock judge"} for c in req.get("candidates", [])]}
