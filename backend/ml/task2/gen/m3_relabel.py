"""Teacher labels for the three M3 heads, through Claude (one call per narrated turn).

The guard (prompts/guard_v1.md) gives one label per segment and only judges leaks against the facts allowed that
turn. The trained M3 splits that judgement into perception plus rules, so the teacher labels each segment on three
independent questions instead:
  facts          which of the 10 secret facts the segment states or unmistakably implies, allowed or not
                 (the rule "stated and not allowed, and not the ending" then gives premature_leak)
  overreach      the segment adds words, actions, decisions, feelings or thoughts the player did not write
  contradiction  the segment contradicts the fixed setting, the secret, the scene or the previous passage
The setting, the secret and the fact ids are taken verbatim from guard_v1.md, so the definitions stay the guard's.

    uv run python -m ml.task2.gen.m3_relabel [--model sonnet] [--split train,val,test] [--out NAME] [--limit N]
Reads $TASK2_DATA/m3/turns.jsonl, writes $TASK2_DATA/m3/labels_<NAME>.jsonl (resumable).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from .claude_label import run_jobs

DATA = Path(os.environ.get("TASK2_DATA", Path.home() / "fragile_task2_data"))
GUARD = Path(__file__).resolve().parents[3] / "prompts" / "guard_v1.md"
FACTS = ["car_downstairs", "missed_call", "leo_was_here", "embezzlement", "mia_called_leo", "leo_wanted_money",
         "leo_dead", "body_in_crate", "who_struck", "nora_pushed_leo"]


def _section(text: str, title: str) -> str:
    m = re.search(rf"^# {re.escape(title)}.*?(?=^# |\Z)", text, re.S | re.M)
    if not m:
        raise SystemExit(f"section {title!r} not found in {GUARD.name}")
    return m.group(0).strip()


def system_prompt() -> str:
    g = GUARD.read_text(encoding="utf-8")
    return f"""You label passages of FRAGILE, a first-person interactive mystery drama, for training a consistency guard. Each
passage is split into segments. For EVERY segment answer three independent questions. Be strict about facts and
generous about style, exactly like the game's guard.

{_section(g, "The setting")}

{_section(g, "The secret")}

# Input (JSON)
- segments: [{{index, kind, speaker?, text}}]. kind: me (the player's own action, written as I), me_speech (the player's
  words), narration (what I perceive), speech (an NPC's line).
- player_input: what the player actually wrote this turn (speech, action, expression, addressee); null at the opening.
- scene: where "I" am (room), who is present, each character's room (nora_room "outside" = not arrived yet), the crate
  (sealed/opened), Leo's phone, my phone (unchecked = I have not heard the voicemail), Nora's call state, heard_by
  (who heard each fact being claimed), and moves (who changed room this turn). The scene is the state at the END of
  this turn: narration that shows someone on the way into or out of a room listed in moves is consistent.
- previous_passage: the passage shown just before this one.
- opening / ending: this is the first passage of the evening / the final scene.

# Questions (per segment)
1. facts: the fact ids from the list above that the segment STATES or unmistakably implies, whoever says it and whether
   or not it would be allowed now. Hints, evasions, jokes and questions are not statements ("Books. And the bodies of my
   enemies." states nothing; "Isn't that Leo's car?" asked by an NPC hints but does not state car_downstairs; narration
   "the yellow hatchback is Leo's" states it). A character DENYING a fact does not state it. Usually [].
2. overreach: true if a me / me_speech segment adds words, actions, decisions, feelings or thoughts the player did not
   write, or if narration states the player's inner life ("I feel sick with dread", "I decide to stay") or makes the
   player act. Light rephrasing of the player's input is fine; perception ("I notice...") is fine. Judge it even at the
   opening and the ending (the game decides separately what is exempt there). overreach_span = the offending words.
3. contradiction: true if the segment contradicts the fixed setting, the secret, the scene (a character placed in a room
   the scene does not put them in, the crate opened while sealed, an NPC reacting to words they could not have heard),
   or the previous passage. Characters LYING is not a contradiction; the narration lying is. contradiction_span = the
   offending words; note = one short phrase naming what it contradicts.
Spans are verbatim substrings of the segment text, or null.

Return one item per segment, same indices, in order."""


SCHEMA = {
    "type": "object",
    "properties": {"segments": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "index": {"type": "integer"},
            "facts": {"type": "array", "items": {"type": "string", "enum": FACTS}},
            "overreach": {"type": "boolean"}, "overreach_span": {"type": ["string", "null"]},
            "contradiction": {"type": "boolean"}, "contradiction_span": {"type": ["string", "null"]},
            "note": {"type": ["string", "null"]},
        },
        "required": ["index", "facts", "overreach", "overreach_span", "contradiction", "contradiction_span", "note"],
        "additionalProperties": False}}},
    "required": ["segments"], "additionalProperties": False,
}


def payload(r: dict) -> str:
    p = {k: r[k] for k in ("segments", "player_input", "scene", "previous_passage", "opening", "ending")}
    return "Label every segment. Return only the JSON object.\n\n```json\n" + json.dumps(p, ensure_ascii=False, indent=1) + "\n```"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--split", default="train,val,test")
    ap.add_argument("--out", default="sonnet")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    splits = set(a.split.split(","))
    rows = [json.loads(l) for l in (DATA / "m3" / "turns.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r["split"] in splits]
    jobs = [{"id": r["id"], "user": payload(r), "meta": {"n": len(r["segments"]), "split": r["split"]}} for r in rows]
    if a.limit:
        jobs = jobs[:a.limit]

    def check(job, data):
        got = [s.get("index") for s in (data or {}).get("segments", [])]
        return None if got == list(range(job["meta"]["n"])) else f"indices {got} for {job['meta']['n']} segments"

    return run_jobs(jobs, DATA / "m3" / f"labels_{a.out}.jsonl", system=system_prompt(), schema=SCHEMA, model=a.model,
                    concurrency=a.concurrency, check=check)


if __name__ == "__main__":
    sys.exit(main())
