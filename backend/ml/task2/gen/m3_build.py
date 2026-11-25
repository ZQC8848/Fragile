"""M3 training examples: one per segment, with the Claude teacher's three labels (train/m3_data.py has the format).

Sources:
  selfplay  every shown segment of the 54 sessions (labels_sonnet.jsonl)
  synth     DeepSeek rewrites, labelled by the teacher (labels_verify_sonnet.jsonl, source synth)
  logged    spans the game's guard rejected, labelled by the teacher (labels_verify_sonnet.jsonl, source logged)
Splits: train / val by session (m3_export.py); test = r1-haosen selfplay only (Claude narrator, never rewritten);
test_logged = the logged spans from r1-haosen, a separate check on the kind of drafts the guard actually rejects.

    uv run python -m ml.task2.gen.m3_build [--out examples]
Writes $TASK2_DATA/m3/<out>/{train,val,test,test_logged}.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from ..train.m3_data import PREV_CHARS, find_span

DATA = Path(os.environ.get("TASK2_DATA", Path.home() / "fragile_task2_data"))


def _labels(lab: dict, text: str, miss: Counter) -> dict:
    out = {"facts": sorted(set(lab["facts"])), "note": lab.get("note")}
    for h in ("overreach", "contradiction"):
        out[h] = bool(lab[h])
        sp = find_span(text, lab.get(f"{h}_span")) if lab[h] else None
        if lab[h] and lab.get(f"{h}_span") and sp is None:
            miss[h] += 1
        out[f"{h}_span"] = list(sp) if sp else None
    return out


def example(r: dict, seg: dict, lab: dict, source: str, split: str, ex_id: str, miss: Counter, **extra) -> dict:
    return {"ex_id": ex_id, "turn_id": r["id"], "session": r["session"], "split": split, "source": source,
            "index": seg["index"], "kind": seg["kind"], "speaker": seg.get("speaker"), "text": seg["text"],
            "player_input": r["player_input"], "scene": r["scene"], "previous_passage": r["previous_passage"][-PREV_CHARS:],
            "opening": r["opening"], "ending": r["ending"], "revealed": r.get("revealed", []),
            "labels": _labels(lab, seg["text"], miss), **extra}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="examples")
    ap.add_argument("--verify", default="labels_verify_sonnet.jsonl")
    a = ap.parse_args()
    m3 = DATA / "m3"
    rows = {r["id"]: r for r in map(json.loads, (m3 / "turns.jsonl").read_text(encoding="utf-8").splitlines())}
    out: dict[str, list[dict]] = {"train": [], "val": [], "test": [], "test_logged": []}
    miss = Counter()
    for d in map(json.loads, (m3 / "labels_sonnet.jsonl").read_text(encoding="utf-8").splitlines()):
        r = rows[d["id"]]
        for seg, lab in zip(r["segments"], d["data"]["segments"]):
            out[r["split"]].append(example(r, seg, lab, "selfplay", r["split"], f"{r['id']}:{seg['index']}", miss))
    vp = m3 / a.verify
    for d in map(json.loads, vp.read_text(encoding="utf-8").splitlines() if vp.exists() else []):
        meta = d["meta"]
        r = rows[meta["turn_id"]]
        seg = {**meta["segment"], "index": meta["target"]}
        lab = d["data"]["segments"][meta["target"]]
        split = r["split"]
        if split == "test":
            if meta["source"] != "logged":
                raise SystemExit(f"{d['id']}: a generated segment from a test session")
            split = "test_logged"
        extra = {k: meta[k] for k in ("mode", "subtype", "logged_label", "logged_fact") if k in meta}
        out[split].append(example(r, seg, lab, meta["source"], split, d["id"], miss, gen=extra))
    dst = m3 / a.out
    dst.mkdir(exist_ok=True)
    for s, exs in out.items():
        (dst / f"{s}.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in exs), encoding="utf-8")
        c = Counter()
        for e in exs:
            c[e["source"]] += 1
            c["facts"] += bool(e["labels"]["facts"]); c["overreach"] += e["labels"]["overreach"]; c["contradiction"] += e["labels"]["contradiction"]
        print(f"{s}: {len(exs)} segments {dict(c)}")
    print(f"teacher spans not found in the text: {dict(miss)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
