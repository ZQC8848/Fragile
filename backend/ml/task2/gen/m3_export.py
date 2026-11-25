"""M3 (narration guard) data: one record per narrated turn from the group's self-play archives.

The archives log the passage the player saw (after any guard rewrite), the player's input and the game state, but
not the guard's input (GuardContext) or the drafts it rejected. So each record carries what the three M3 heads need:
  - segments: the shown passage, [{index, kind, speaker, text}]
  - player_input: speech / action / expression / addressee this turn (None at the opening)
  - scene: rooms, who is present, crate, phones, Nora's call, heard_by, and who moved this turn (from the previous state)
  - previous_passage: the text of the passage before, for "contradicts what was just said"
  - opening / ending flags (the guard exempts authored player actions there)
  - revealed: facts revealed by the end of the turn (GuardContext.allowed is not logged; this stands in for it)
plus the logged guard verdicts (the first attempt's failures keep their offending span: real positives) and the split.

    uv run python -m ml.task2.gen.m3_export [--raw DIR]
Reads $TASK2_DATA/m3/raw/<session>/turns.jsonl, writes $TASK2_DATA/m3/turns.jsonl.
Split: base20 and carc-test20 (DeepSeek narrator) by session into train / val (5 sessions); r1-haosen (Claude narrator) = test.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

DATA = Path(os.environ.get("TASK2_DATA", Path.home() / "fragile_task2_data"))
NPCS = ("julian", "mia", "nora")
SCENE_KEYS = ("crate", "leo_phone", "player_phone", "nora_call")
N_VAL = 5  # validation sessions, the first N of the DeepSeek-narrator sessions by a fixed hash


def _h(session: str) -> str:
    return hashlib.sha1(session.encode()).hexdigest()


def splits_for(sessions: list[str]) -> dict[str, str]:
    dev = sorted((s for s in sessions if not s.startswith("r1-haosen")), key=_h)
    val = set(dev[:N_VAL])
    return {s: "test" if s.startswith("r1-haosen") else "val" if s in val else "train" for s in sessions}


def scene_of(state: dict, prev: dict | None) -> dict:
    room = state.get("player_room")
    rooms = {n: state.get(f"{n}_room") for n in NPCS}
    moves = []
    if prev:
        if prev.get("player_room") != room:
            moves.append({"who": "me", "from": prev.get("player_room"), "to": room})
        moves += [{"who": n, "from": prev.get(f"{n}_room"), "to": r} for n, r in rooms.items() if prev.get(f"{n}_room") != r]
    return {"room": room, "present": [n for n, r in rooms.items() if r == room],
            **{f"{n}_room": r for n, r in rooms.items()}, **{k: state.get(k) for k in SCENE_KEYS},
            "heard_by": state.get("heard_by") or {}, "moves": moves}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=DATA / "m3" / "raw")
    a = ap.parse_args()
    out, n_seg = [], 0
    files = sorted(a.raw.glob("*/turns.jsonl"))
    split = splits_for([f.parent.name for f in files])
    for tf in files:
        session = tf.parent.name
        turns = [json.loads(l) for l in tf.read_text(encoding="utf-8").splitlines() if l.strip()]
        prev_state, prev_text, ended = None, "", False
        for t in turns:
            nar, state = t.get("narrator") or {}, t.get("state") or {}
            segs = [{"index": i, "kind": s.get("kind"), "speaker": s.get("speaker"), "text": s.get("text", "")}
                    for i, s in enumerate(nar.get("segments") or [])]
            ending = bool(state.get("ending")) and not ended
            ended = ended or bool(state.get("ending"))
            inp = t.get("input") or None
            ch = (inp or {}).get("channels") or None
            guard = t.get("guard") or []
            first = ((guard[0].get("verdicts") or {}).get("result") or {}).get("verdicts", []) if guard else []
            last = ((guard[-1].get("verdicts") or {}).get("result") or {}).get("verdicts", []) if guard else []
            if segs:
                out.append({
                    "id": f"{session}:{t['turn']}", "session": session, "round": session.rsplit("-", 1)[0], "turn": t["turn"],
                    "split": split[session], "segments": segs,
                    "player_input": ({k: ch.get(k) or "" for k in ("speech", "action", "expression")} | {"addressee": ch.get("addressee")}) if ch else None,
                    "scene": scene_of(state, prev_state), "previous_passage": prev_text,
                    "opening": t["turn"] == 0, "ending": ending,
                    # facts revealed by the end of this turn: the closest logged stand-in for GuardContext.allowed
                    "revealed": sorted(state.get("revealed") or []),
                    "narrator_model": (nar.get("meta") or {}).get("model"), "rewrites": nar.get("rewrites", 0), "repaired": nar.get("repaired", False),
                    "first_failures": [v for v in first if v.get("label") != "consistent"],
                    "last_verdicts": last if not nar.get("rewrites") or len(guard) > 1 else [],
                })
                n_seg += len(segs)
            prev_state, prev_text = state, " ".join(s["text"] for s in segs)
    path = DATA / "m3" / "turns.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    by = {}
    for r in out:
        by.setdefault(r["split"], [set(), 0, 0])
        by[r["split"]][0].add(r["session"]); by[r["split"]][1] += 1; by[r["split"]][2] += len(r["segments"])
    for s, (ss, nt, ns) in sorted(by.items()):
        print(f"{s}: {len(ss)} sessions, {nt} turns, {ns} segments")
    print(f"total {len(out)} turns, {n_seg} segments -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
