"""Average several M3 runs (e.g. three seeds) from the predictions they saved, and score the average like any system.

Probabilities (facts, overreach, contradiction) are averaged; a fact counts when its mean is >= 0.5; a character is in
a predicted span when more than half of the members put it there. Thresholds are tuned on the real-source val examples
(m3_metrics.REAL_SOURCES), as for the members.

    python -m ml.task2.train.m3_ensemble --data DATA --runs RUNS --members m3_r9_s0 m3_r9_s1 m3_r9_s2 --name m3_r9_ens
Reads RUNS/<member>/preds_<split>.jsonl (written by m3_metrics.evaluate); writes RUNS/<name>/metrics.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .m3_data import BINARY, FACTS, load_splits
from .m3_metrics import REAL_SOURCES, evaluate


def _chars(spans: list[list[int]], n: int) -> set[int]:
    return {i for s, t in spans for i in range(max(0, s), min(t, n))}


def _intervals(chars: set[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for i in sorted(chars):
        if out and i == out[-1][1]:
            out[-1][1] = i + 1
        else:
            out.append([i, i + 1])
    return out


def average(members: list[dict[str, Any]], text: str) -> dict[str, Any]:
    k = len(members)
    pf = [sum(m["p_facts"][j] for m in members) / k for j in range(len(FACTS))]
    out: dict[str, Any] = {"facts": [f for f, p in zip(FACTS, pf) if p >= 0.5], "p_facts": [round(p, 4) for p in pf]}
    for h in BINARY:
        out[f"p_{h}"] = sum(m[f"p_{h}"] for m in members) / k
        votes: dict[int, int] = {}
        for m in members:
            for i in _chars(m.get(f"{h}_span") or [], len(text)):
                votes[i] = votes.get(i, 0) + 1
        out[f"{h}_span"] = _intervals({i for i, v in votes.items() if v * 2 > k})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--runs", required=True)
    ap.add_argument("--members", nargs="+", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    splits = load_splits(a.data)
    runs = Path(a.runs)
    have = [s for s in splits if all((runs / m / f"preds_{s}.jsonl").exists() for m in a.members)]
    by_id: dict[str, list[dict[str, Any]]] = {}
    for m in a.members:
        for s in have:
            for line in (runs / m / f"preds_{s}.jsonl").read_text(encoding="utf-8").splitlines():
                d = json.loads(line)
                by_id.setdefault(f"{s}|{d['ex_id']}", []).append(d)
    # members score the same examples; a run with --smoke scores only the first examples of each split
    splits = {s: [e for e in splits[s] if len(by_id.get(f"{s}|{e['ex_id']}", [])) == len(a.members)] for s in have}
    for s in have:
        n_any = sum(k.startswith(f"{s}|") for k in by_id)
        if n_any != len(splits[s]):
            raise SystemExit(f"{s}: members predicted different examples ({n_any} seen, {len(splits[s])} predicted by all)")
    splits = {s: exs for s, exs in splits.items() if exs}
    ens = {s: [average(by_id[f"{s}|{e['ex_id']}"], e["text"]) for e in exs] for s, exs in splits.items()}
    lookup = {id(exs): ens[s] for s, exs in splits.items()}
    meta = [json.loads((runs / m / "metrics.json").read_text(encoding="utf-8")) for m in a.members]
    evaluate(a.name, splits, lambda exs: lookup[id(exs)], a.runs,
             {"rung": 4, "method": f"mean of {len(a.members)} runs: {', '.join(a.members)}", "members": a.members,
              "n_train": meta[0].get("n_train"), "member_best_val_score": [x.get("best_val_score") for x in meta]},
             tune_sources=REAL_SOURCES)


if __name__ == "__main__":
    main()
