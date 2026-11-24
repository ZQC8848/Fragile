"""Relabel `nora_answer` with the review v2 rule (plan.md R31: "he came and went" is a lie), through Claude.

Only turns that carry a Nora label under v1 are relabelled: v2 changes which way an answer counts, not which
inputs are addressed to Nora. Ten turns per call.

    uv run python -m ml.task2.gen.relabel_nora_v2 [--model sonnet] [--limit N]
Writes $TASK2_DATA/relabel/nora_v2.jsonl (one line per batch; resumable).
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
SPLITS = ("train", "val", "test", "test_v1", "seeds")
PROMPT = Path(__file__).resolve().parents[3] / "prompts" / "review_v2.md"


def nora_rule() -> str:
    text = PROMPT.read_text(encoding="utf-8")
    m = re.search(r"- \*\*nora_answer\*\*.*?(?=\n# |\Z)", text, re.S)
    if not m:
        raise SystemExit("nora_answer rule not found in review_v2.md")
    return m.group(0).strip()


SYSTEM = """You label one field of a dataset for FRAGILE, a first-person interactive mystery. The player is at Julian and Mia's
farewell dinner. Leo, their friend, came this afternoon and is dead in the crate; his sister Nora is looking for him and
calls, texts or comes to the door. For each player input below, decide `nora_answer` exactly by this rule:

{rule}

Every input given to you IS addressed to Nora (speech to her, a call or a text to her), so answer "truth", "lie" or
"none", never null. Inputs may be in English, Chinese or a mix. `context` is the scene just before the input.
Return one item per input, with the same id."""

SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"}, "nora_answer": {"type": "string", "enum": ["truth", "lie", "none"]}},
        "required": ["id", "nora_answer"], "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--batch", type=int, default=10)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="only the first N batches (smoke test)")
    a = ap.parse_args()
    rows, seen = [], set()
    for split in SPLITS:
        p = DATA / "examples_v2" / f"{split}.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r["turn_labels"].get("nora_answer") is None or r["ex_id"] in seen:
                continue
            seen.add(r["ex_id"])
            rows.append({"id": r["ex_id"], "context": r.get("context_text", ""), "input": r["text"], "v1": r["turn_labels"]["nora_answer"]})
    rows.sort(key=lambda r: r["id"])
    jobs = []
    for i in range(0, len(rows), a.batch):
        chunk = rows[i:i + a.batch]
        user = "Label every input.\n\n```json\n" + json.dumps([{k: r[k] for k in ("id", "context", "input")} for r in chunk],
                                                             ensure_ascii=False, indent=1) + "\n```"
        jobs.append({"id": f"b{i // a.batch:04d}", "user": user, "meta": {"ids": [r["id"] for r in chunk], "v1": [r["v1"] for r in chunk]}})
    if a.limit:
        jobs = jobs[:a.limit]
    print(f"{len(rows)} Nora-labelled turns in {len(jobs)} batches", flush=True)

    def check(job, data):
        got = {it["id"] for it in (data or {}).get("items", [])}
        missing = set(job["meta"]["ids"]) - got
        return f"missing {len(missing)} ids" if missing else None

    return run_jobs(jobs, DATA / "relabel" / "nora_v2.jsonl", system=SYSTEM.format(rule=nora_rule()), schema=SCHEMA,
                    model=a.model, concurrency=a.concurrency, check=check)


if __name__ == "__main__":
    sys.exit(main())
