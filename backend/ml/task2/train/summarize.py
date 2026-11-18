"""Collect runs/*/metrics.json into one markdown comparison table (for the midterm report).

    python -m task2.train.summarize --runs RUNS [--split test] [--consistency path/to/consistency.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

COLS = [
    ("act_set_microF1", "acts µF1"), ("act_set_macroF1", "acts macro-F1"), ("topics_microF1", "topics µF1"),
    ("claims_microF1", "claims µF1"), ("addressee_acc", "addressee acc"), ("action_acc", "action acc"),
    ("suspicion_MAE", "suspicion MAE"), ("suspicion_QWK", "suspicion QWK"), ("nora_acc", "nora acc"),
    ("side_acc", "side acc"), ("seg_charF1", "seg char-F1"),
]


def fmt(v) -> str:
    return "—" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--by-lang", action="store_true")
    args = ap.parse_args()
    rows = []
    for p in sorted(Path(args.runs).glob("*/metrics.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        sp = m["splits"].get(args.split)
        if not sp:
            continue
        rows.append((m.get("rung", "?"), m["system"], sp["n"], sp["headline"], sp.get("by_lang", {})))
    rows.sort(key=lambda r: (str(r[0]), r[1]))
    head = "| rung | system | n | " + " | ".join(c[1] for c in COLS) + " |"
    print(f"Split: {args.split}. Labels: teacher (review v1) unless noted.\n")
    print(head)
    print("|" + "---|" * (3 + len(COLS)))
    for rung, name, n, h, _ in rows:
        print(f"| {rung} | {name} | {n} | " + " | ".join(fmt(h.get(k)) for k, _ in COLS) + " |")
    if args.by_lang:
        print("\nBy language (acts µF1 / addressee acc / seg char-F1):\n")
        for rung, name, n, h, bl in rows:
            cells = [f"{lang}: {fmt(v.get('act_set_microF1'))} / {fmt(v.get('addressee_acc'))} / {fmt(v.get('seg_charF1'))}" for lang, v in sorted(bl.items())]
            print(f"- {name}: " + "; ".join(cells))


if __name__ == "__main__":
    main()
