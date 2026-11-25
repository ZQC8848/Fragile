"""Agreement between two M3 teachers on the turns both labelled (e.g. Opus on a test sample vs Sonnet).

The second teacher is scored as if it were a system against the first, with the same metrics as the models, so the
numbers read as a ceiling: a student cannot be expected to agree with Sonnet more than Opus does.

    python -m ml.task2.gen.m3_agreement [--gold opus --pred sonnet] [--out RUNS]
Reads $TASK2_DATA/m3/examples/test.jsonl and labels_<name>.jsonl; with --out writes RUNS/m3_teacher_<pred>_vs_<gold>/metrics.json.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ..train.m3_data import find_span, load_splits
from ..train.m3_metrics import evaluate, headline, score

DATA = Path(os.environ.get("TASK2_DATA", Path.home() / "fragile_task2_data"))


def _labels(name: str) -> dict[str, list[dict]]:
    return {d["id"]: d["data"]["segments"] for d in map(json.loads, (DATA / "m3" / f"labels_{name}.jsonl").read_text(encoding="utf-8").splitlines())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="opus")
    ap.add_argument("--pred", default="sonnet")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    gold, pred = _labels(a.gold), _labels(a.pred)
    both = set(gold) & set(pred)
    test = [e for e in load_splits(DATA / "m3" / "examples")["test"] if e["turn_id"] in both]
    exs, preds = [], []
    for e in test:
        g = gold[e["turn_id"]][e["index"]]
        p = pred[e["turn_id"]][e["index"]]
        lab = {"facts": sorted(set(g["facts"])), "note": g.get("note")}
        for h in ("overreach", "contradiction"):
            lab[h] = bool(g[h])
            sp = find_span(e["text"], g.get(f"{h}_span")) if g[h] else None
            lab[f"{h}_span"] = list(sp) if sp else None
        exs.append({**e, "labels": lab})
        q = {"facts": sorted(set(p["facts"])), "overreach": bool(p["overreach"]), "contradiction": bool(p["contradiction"])}
        for h in ("overreach", "contradiction"):
            sp = find_span(e["text"], p.get(f"{h}_span")) if p[h] else None
            if sp:
                q[f"{h}_span"] = [list(sp)]
        preds.append(q)
    print(f"{len(both)} turns, {len(exs)} segments labelled by both {a.gold} and {a.pred}")
    for k, v in headline(score(exs, preds)).items():
        if isinstance(v, float):
            print(f"  {k}: {v:.3f}")
    if a.out:
        evaluate(f"m3_teacher_{a.pred}_vs_{a.gold}", {"test_sample": exs}, lambda xs: preds if xs is exs else [], a.out,
                 {"rung": "teacher", "method": f"{a.pred} labels scored against {a.gold} on {len(both)} test turns", "n_train": 0})


if __name__ == "__main__":
    main()
