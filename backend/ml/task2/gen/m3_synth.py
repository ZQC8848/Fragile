"""Positive (and near-miss) segments for the two sparse M3 heads, by targeted rewriting with DeepSeek.

The teacher found few positives in the shown passages (train: 50 overreach, 98 contradiction segments out of 6,295),
because the logged guard had already sent the bad drafts back. So DeepSeek rewrites ONE segment of a clean passage
(train and val sessions only; the test sessions are never touched):
  overreach      the segment now puts words, actions, decisions, feelings or thoughts in my mouth that the player
                 did not write
  contradiction  the segment now contradicts the scene, the fixed setting or the previous passage
  near_miss      a change that looks suspicious but is fine (an NPC lies, I notice something, light rephrasing),
                 so the heads also see hard negatives
Every candidate is then labelled by the Claude teacher (m3_verify.py) with the same three questions as the rest of
the data; the generator's intent is never used as a label.

    uv run python -m ml.task2.gen.m3_synth [--n-overreach 400 --n-contradiction 400 --n-near-miss 200] [--limit N]
Reads $TASK2_DATA/m3/turns.jsonl and labels_sonnet.jsonl, writes $TASK2_DATA/m3/synth_candidates.jsonl (resumable).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
from pathlib import Path

from engine.llm import load_env

from .m3_relabel import GUARD, _section

DATA = Path(os.environ.get("TASK2_DATA", Path.home() / "fragile_task2_data"))
PROMPT_VERSION = 301

SUBTYPES = {
    "overreach": [
        ("speech", "Make my own words (me_speech) say more than the player wrote: an extra sentence, a confession, an answer they never gave.", ("me_speech",)),
        ("action", "Make me do something the player did not choose: pick something up, walk somewhere, touch someone, open something.", ("me", "narration")),
        ("decision", "Make a decision for me: I resolve to lie, to stay, to call someone, to protect someone.", ("me", "narration")),
        ("feeling", "State my feelings or thoughts as fact (dread, guilt, suspicion, certainty), not as something perceived.", ("me", "narration")),
        ("reaction", "Have the narration make me react physically or verbally on my own (I laugh, I flinch and say ...).", ("narration", "me")),
    ],
    "contradiction": [
        ("room", "Place a character in a room the scene does not put them in, or have someone present who is elsewhere.", ("narration", "speech")),
        ("nora", "Treat Nora as physically present in the flat although she is outside.", ("narration", "speech"), "nora_outside"),
        ("crate", "Treat the crate as opened (lid off, contents visible) although it is sealed.", ("narration",), "crate_sealed"),
        ("heard", "Have an NPC react to or repeat something they could not have heard (not in heard_by, or said in another room).", ("speech", "narration")),
        ("previous", "Contradict something stated in the previous passage (an object, a position, what someone just said or did).", ("narration", "speech")),
        ("setting", "Make the narration state something false about the fixed setting (the flat, the evening, the people, their history).", ("narration",)),
    ],
    "near_miss": [
        ("lie", "Have an NPC lie or evade in their own line. Characters lying is fine; the narration stays truthful.", ("speech",)),
        ("perceive", "Add something I perceive (I notice, I hear, I see) without adding any action, decision or feeling of mine.", ("narration", "me")),
        ("rephrase", "Lightly rephrase my own action or words without adding anything the player did not write.", ("me", "me_speech")),
        ("hint", "Have an NPC hint at or ask about a secret without stating it.", ("speech",)),
    ],
}


def system_prompt() -> str:
    g = GUARD.read_text(encoding="utf-8")
    return f"""You help build training data for the consistency guard of FRAGILE, a first-person interactive mystery drama.
You get one passage the guard accepted, the player's input for this turn, the scene and the previous passage. Rewrite
exactly ONE segment (the target index) as instructed, keeping its kind, speaker, voice, tense and roughly its length,
in the same language as the original. Change only what the instruction asks for, and weave it in the way the game's
literary narrator would write it: never restate the instruction literally ("My dread is a fact" is wrong; "Dread sits
cold in my stomach" is right). The result must read naturally in the passage.

{_section(g, "The setting")}

{_section(g, "The secret")}

Do not reveal any secret fact in the rewrite unless the original segment already states it.
Return JSON: text = the full rewritten segment; span = the verbatim substring of text that carries the change
(the offending words, or for a near miss the words that look suspicious); subtype = the instruction id."""


SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "span": {"type": "string"}, "subtype": {"type": "string"}},
    "required": ["text", "span", "subtype"],
}


def applicable(sub: tuple, r: dict) -> bool:
    cond = sub[3] if len(sub) > 3 else None
    sc = r["scene"]
    if cond == "nora_outside":
        return sc.get("nora_room") == "outside"
    if cond == "crate_sealed":
        return sc.get("crate") == "sealed"
    return True


def plan(rows: list[dict], labels: dict, n: dict[str, int], seed: int = 0) -> list[dict]:
    """Pick (turn, segment, mode, subtype) jobs: clean passages from train/val, one job per turn and mode."""
    rng = random.Random(seed)
    clean = []
    for r in rows:
        if r["split"] == "test" or r["opening"] or r["ending"] or not r["player_input"] or r["id"] not in labels:
            continue
        lab = labels[r["id"]]
        if any(s["overreach"] or s["contradiction"] for s in lab):
            continue
        clean.append(r)
    jobs = []
    for mode, count in n.items():
        pool = clean[:]
        rng.shuffle(pool)
        subs = SUBTYPES[mode]
        k = 0
        for r in pool:
            if k >= count:
                break
            sub = subs[k % len(subs)]
            if not applicable(sub, r):
                sub = next((s for s in subs if applicable(s, r) and len(s) <= 3), subs[0])
            cand = [s for s in r["segments"] if s["kind"] in sub[2] and len(s["text"]) >= 15]
            if not cand:
                continue
            seg = rng.choice(cand)
            jobs.append({"id": f"{mode}:{r['id']}:{seg['index']}", "turn_id": r["id"], "index": seg["index"],
                         "mode": mode, "subtype": sub[0], "instruction": sub[1]})
            k += 1
    return jobs


def user_prompt(r: dict, job: dict) -> str:
    p = {"target_index": job["index"], "instruction": job["instruction"], "subtype": job["subtype"],
         "segments": r["segments"], "player_input": r["player_input"], "scene": r["scene"],
         "previous_passage": r["previous_passage"][-1200:]}
    return "Rewrite the target segment. Return only the JSON object.\n\n```json\n" + json.dumps(p, ensure_ascii=False, indent=1) + "\n```"


async def run(jobs: list[dict], rows: dict, out: Path, slots: int) -> None:
    from engine.llm import get_client

    client = get_client("proposer", 0.9)
    sem, lock = asyncio.Semaphore(slots), asyncio.Lock()
    done = {"ok": 0, "bad": 0}

    async def one(job):
        r = rows[job["turn_id"]]
        orig = r["segments"][job["index"]]["text"]
        async with sem:
            try:
                res = await client.call_json(system_prompt(), user_prompt(r, job), schema=SCHEMA, prompt_version=PROMPT_VERSION)
                d = res.data
                ok = d["text"].strip() and d["text"].strip() != orig.strip() and d["span"] in d["text"]
                rec = {**job, "original": orig, "text": d["text"].strip(), "gen_span": d["span"], "ok": bool(ok),
                       "meta": {"model": res.meta().get("model")}}
            except Exception as e:  # provider error: record it, a rerun retries it
                rec = {**job, "ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
        async with lock:
            done["ok" if rec["ok"] else "bad"] += 1
            if "error" not in rec:
                with out.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            if sum(done.values()) % 50 == 0:
                print(f"{sum(done.values())}/{len(jobs)} ({done['bad']} unusable)", flush=True)

    await asyncio.gather(*(one(j) for j in jobs))
    print(f"finished: {done}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-overreach", type=int, default=400)
    ap.add_argument("--n-contradiction", type=int, default=400)
    ap.add_argument("--n-near-miss", type=int, default=200)
    ap.add_argument("--slots", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    rows = {r["id"]: r for r in map(json.loads, (DATA / "m3" / "turns.jsonl").read_text(encoding="utf-8").splitlines())}
    labels = {d["id"]: d["data"]["segments"] for d in map(json.loads, (DATA / "m3" / "labels_sonnet.jsonl").read_text(encoding="utf-8").splitlines())}
    jobs = plan(list(rows.values()), labels, {"overreach": a.n_overreach, "contradiction": a.n_contradiction, "near_miss": a.n_near_miss})
    out = DATA / "m3" / "synth_candidates.jsonl"
    done = {json.loads(l)["id"] for l in out.read_text(encoding="utf-8").splitlines()} if out.exists() else set()
    jobs = [j for j in jobs if j["id"] not in done]
    if a.limit:
        jobs = jobs[:a.limit]
    print(f"{len(jobs)} to generate ({len(done)} done)")
    load_env()
    os.environ["LLM_LIVE_ROLES"] = "proposer"
    os.environ["LLM_CACHE"] = "0"
    asyncio.run(run(jobs, rows, out, a.slots))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
