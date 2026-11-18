"""Turn raw records + segmentation relabels into training examples (untokenised, one JSON per line).

    uv run python -m ml.task2.gen.build_examples --runs pilot b1 --out all.jsonl

An example keeps the original text and character spans, so the tokenizer can be chosen on CARC.
Rows without a usable teacher label (silence, rule-precheck rejections, fallbacks) are left out; silence is
handled by a rule at inference time. `validity` is kept for analysis only: it belongs to task 3.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from ..common.labels import SCHEMA_VERSION
from .relabel_tagged import rec_id
from .run_selfplay import DATA_ROOT


def context_text(ctx: dict[str, Any]) -> str:
    asking = ctx.get("asking") or {}
    parts = [
        f"room={ctx.get('player_room')}",
        f"present={','.join(ctx.get('present') or []) or 'nobody'}",
        f"phase={ctx.get('story_phase')}",
    ]
    if ctx.get("phone_ringing"):
        parts.append("phone=ringing")
    if ctx.get("on_call_with_nora"):
        parts.append("on_call=nora")
    if asking:
        parts.append(f"asking={asking.get('asker')}:{asking.get('kind')}")
    lines = " | ".join(ctx.get("recent_npc_lines") or [])
    return "; ".join(parts) + (f" || {lines}" if lines else "")


def build(r: dict[str, Any], rl: dict[str, Any] | None) -> dict[str, Any] | None:
    t = r["teacher"]
    if not t or t["fallback"] or not r["input"]:
        return None
    data = t["data"]
    mode = r["input"]["mode"]
    if rl is None or rl["method"] == "drop":
        text = r["input"]["text"] if mode == "single" else rl["text"] if rl else None
        if text is None:
            return None
        segments, unit_spans, seg_ok = [], [None] * len(data.get("units") or []), False
    else:
        text, segments, unit_spans, seg_ok = rl["text"], rl["segments"], rl["unit_spans"], True
    units = []
    for u, sp in zip(data.get("units") or [], unit_spans):
        units.append({
            "channel": u.get("channel"), "start": sp[0] if sp else None, "end": sp[1] if sp else None,
            "act": u.get("act"), "addressee": u.get("addressee"), "topics": u.get("topics") or [],
            "action": u.get("action"), "implausible": bool(u.get("implausible")), "text_teacher": u.get("text"),
        })
    asking = (r["context"] or {}).get("asking") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "ex_id": rec_id(r), "session": r["session"], "turn": r["turn"], "run": r["run"],
        "source": r.get("source", "selfplay"), "lang": r["lang"], "mode": mode,
        "text": text, "context_text": context_text(r["context"] or {}), "context": r["context"],
        "segments": segments,
        "units": units,
        "turn_labels": {
            "addressee": (data.get("channels") or {}).get("addressee"),
            "suspicion": data.get("suspicion"), "claims": data.get("claims") or [], "coverage": data.get("coverage"),
            "nora_answer": data.get("nora_answer"), "side_answer": data.get("side_answer"), "translated": data.get("translated"),
        },
        "mask": {
            "seg": seg_ok and mode == "single",
            "units": seg_ok and all(u["start"] is not None for u in units) and bool(units),
            "addressee": mode == "single",  # in channels mode the player chose it: an input, not a label
            "nora": data.get("nora_answer") is not None,
            "side": asking.get("kind") == "side",
        },
        "validity": data.get("validity"),
        "rule": r.get("rule"),
        "persona": r.get("persona"), "violate_requested": r.get("violate_requested"),
        "seg_method": rl["method"] if rl else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", required=True)
    ap.add_argument("--out", default="all.jsonl")
    args = ap.parse_args()
    out_dir = DATA_ROOT / "examples"
    out_dir.mkdir(parents=True, exist_ok=True)
    examples, skipped = [], Counter()
    for run in args.runs:
        rows = [json.loads(x) for x in (DATA_ROOT / "raw" / run / "turns.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        rl_path = DATA_ROOT / "relabel" / f"{run}.jsonl"
        rls = {}
        if rl_path.exists():
            for x in rl_path.read_text(encoding="utf-8").splitlines():
                if x.strip():
                    d = json.loads(x)
                    rls[d["id"]] = d
        for r in rows:
            ex = build(r, rls.get(rec_id(r)))
            if ex is None:
                skipped["no_teacher_or_silence"] += 1
            else:
                examples.append(ex)
    (out_dir / args.out).write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in examples), encoding="utf-8")
    m = Counter()
    for e in examples:
        for k, v in e["mask"].items():
            m[k] += bool(v)
    print(f"{len(examples)} examples -> {out_dir / args.out}; skipped {dict(skipped)}")
    print("mask counts:", dict(m))
    print("lang:", dict(Counter(e["lang"] for e in examples)), " mode:", dict(Counter(e["mode"] for e in examples)))


if __name__ == "__main__":
    main()
