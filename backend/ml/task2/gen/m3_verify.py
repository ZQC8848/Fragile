"""Teacher labels for the extra M3 segments, with the same Claude prompt and questions as m3_relabel.py.

Two sources of extra segments:
  synth   DeepSeek rewrites from m3_synth.py (train / val sessions): the passage with the one segment replaced
  logged  the spans the game's own guard rejected on the first attempt (first_failures): the drafts themselves were
          not logged, so the span is inserted into the shown passage at its index as a segment of a guessed kind;
          from test sessions these form the separate evaluation split test_logged, never training data
The teacher labels the whole passage (context stays honest); only the target segment's label is kept. What the
generator or the logged guard meant is never used as the label.

    uv run python -m ml.task2.gen.m3_verify [--model sonnet] [--limit N]
Writes $TASK2_DATA/m3/labels_verify_<model>.jsonl (resumable). Usage limit: exit 3, run under label_supervise.sh.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .claude_label import run_jobs
from .m3_relabel import SCHEMA, payload, system_prompt

DATA = Path(os.environ.get("TASK2_DATA", Path.home() / "fragile_task2_data"))
LOGGED_LABELS = ("player_overreach", "contradiction", "premature_leak")


def guess_kind(span: str, label: str) -> str:
    s = span.strip()
    if s[:1] in "\"“'‘「":
        return "me_speech" if label == "player_overreach" else "narration"
    if label == "player_overreach" and (s.startswith("I ") or s.startswith("I'") or s.startswith("My ")):
        return "me"
    return "narration"


def jobs_synth(rows: dict) -> list[dict]:
    p = DATA / "m3" / "synth_candidates.jsonl"
    out = []
    for c in map(json.loads, p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        if not c.get("ok"):
            continue
        r = rows[c["turn_id"]]
        segs = [dict(s) for s in r["segments"]]
        segs[c["index"]] = {**segs[c["index"]], "text": c["text"]}
        out.append({"id": c["id"], "turn": {**r, "segments": segs}, "target": c["index"], "source": "synth",
                    "extra": {"mode": c["mode"], "subtype": c["subtype"], "gen_span": c["gen_span"]}})
    return out


def jobs_logged(rows: dict) -> list[dict]:
    out = []
    for r in rows.values():  # test sessions too: their rejected spans become the separate split test_logged
        for k, v in enumerate(r.get("first_failures") or []):
            span = (v.get("span") or "").strip()
            if v.get("label") not in LOGGED_LABELS or len(span) < 8:
                continue
            at = min(int(v.get("index") or 0), len(r["segments"]))
            seg = {"index": at, "kind": guess_kind(span, v["label"]), "speaker": None, "text": span}
            segs = r["segments"][:at] + [seg] + r["segments"][at:]
            segs = [{**s, "index": i} for i, s in enumerate(segs)]
            out.append({"id": f"logged:{r['id']}:{k}", "turn": {**r, "segments": segs}, "target": at, "source": "logged",
                        "extra": {"logged_label": v["label"], "logged_fact": v.get("fact")}})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", choices=("synth", "logged"), default=None)
    a = ap.parse_args()
    rows = {r["id"]: r for r in map(json.loads, (DATA / "m3" / "turns.jsonl").read_text(encoding="utf-8").splitlines())}
    cands = ([] if a.only == "synth" else jobs_logged(rows)) + ([] if a.only == "logged" else jobs_synth(rows))
    jobs = [{"id": c["id"], "user": payload(c["turn"]),
             "meta": {"n": len(c["turn"]["segments"]), "target": c["target"], "source": c["source"],
                      "turn_id": c["turn"]["id"], "segment": c["turn"]["segments"][c["target"]], **c["extra"]}}
            for c in cands]
    if a.limit:
        jobs = jobs[:a.limit]

    def check(job, data):
        got = [s.get("index") for s in (data or {}).get("segments", [])]
        return None if got == list(range(job["meta"]["n"])) else f"indices {got} for {job['meta']['n']} segments"

    return run_jobs(jobs, DATA / "m3" / f"labels_verify_{a.model}.jsonl", system=system_prompt(), schema=SCHEMA,
                    model=a.model, concurrency=a.concurrency, check=check)


if __name__ == "__main__":
    sys.exit(main())
