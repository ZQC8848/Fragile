"""Collect M3 runs (runs/*/metrics.json written by m3_metrics.evaluate) into markdown tables.

    python -m ml.task2.train.m3_summarize --runs RUNS [--split test] [--fixed]
By default the binary heads use the thresholds chosen on val ("tuned") where a run has them; --fixed uses 0.5.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TABLES = {
    "Perception (against the Claude teacher)": [
        ("facts_microF1", "facts µF1"), ("facts_macroF1", "facts macro-F1"),
        ("overreach_P", "overreach P"), ("overreach_R", "overreach R"), ("overreach_AP", "overreach AP"),
        ("contradiction_P", "contra. P"), ("contradiction_R", "contra. R"), ("contradiction_AP", "contra. AP"),
        ("overreach_spanF1", "overreach span F1"), ("contradiction_spanF1", "contra. span F1"),
    ],
    "Composed guard verdicts (game rules, allowed = revealed by end of turn)": [
        ("verdict_macroF1", "verdict macro-F1"), ("leak_recall", "leak recall"), ("verdict_false_alarm", "segment false alarm"),
        ("passage_F1", "passage reject F1"), ("passage_false_reject", "passage false reject"),
    ],
}


def fmt(v) -> str:
    return "—" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True)
    ap.add_argument("--split", default="test")
    ap.add_argument("--fixed", action="store_true")
    a = ap.parse_args()
    rows = []
    for p in sorted(Path(a.runs).glob("*/metrics.json")):
        m = json.loads(p.read_text(encoding="utf-8"))
        sp = (m.get("splits") or {}).get(a.split)
        if not sp or "facts_microF1" not in sp.get("headline", {}):
            continue
        tuned = not a.fixed and "headline_tuned" in sp
        rows.append((str(m.get("rung", "?")), m["system"], sp["n"], sp["headline_tuned" if tuned else "headline"],
                     m.get("tuned_thresholds") if tuned else None))
    rows.sort(key=lambda r: (r[0], r[1]))
    print(f"Split: {a.split}. Labels: Claude teacher (sonnet). Thresholds: {'0.5' if a.fixed else 'chosen on val where available, else 0.5'}.\n")
    for title, cols in TABLES.items():
        print(f"**{title}**\n")
        print("| rung | system | n | " + " | ".join(c[1] for c in cols) + " |")
        print("|" + "---|" * (3 + len(cols)))
        for rung, name, n, h, _ in rows:
            print(f"| {rung} | {name} | {n} | " + " | ".join(fmt(h.get(k)) for k, _ in cols) + " |")
        print()
    th = [(name, t) for _, name, _, _, t in rows if t]
    if th:
        print("Thresholds chosen on val: " + "; ".join(f"{n}: " + ", ".join(f"{k} {v}" for k, v in t.items()) for n, t in th))


if __name__ == "__main__":
    main()
