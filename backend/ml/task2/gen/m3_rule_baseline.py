"""M3 rule baseline: the game's own rule guard (engine/models/guard.py), read as the three perceptions.

  facts          every FACT_PATTERNS regex that matches the segment
  overreach      rule_verdicts' player_overreach (my speech not overlapping the input by 60%, or a me segment when
                 the player gave no action or expression), with every fact allowed so leaks do not mask it
  contradiction  never (the rule path does not judge contradictions)

    uv run python -m ml.task2.gen.m3_rule_baseline --data DATA --out RUNS
"""
from __future__ import annotations

import argparse

from engine.models.guard import FACT_PATTERNS, GuardContext, rule_verdicts

from ..train.m3_data import FACTS, load_splits
from ..train.m3_metrics import evaluate


def predict(exs):
    out = []
    for e in exs:
        ctx = GuardContext(allowed=set(FACTS), player=e.get("player_input") or {}, opening=e["opening"], ending=False)
        v = rule_verdicts([{"kind": e["kind"], "speaker": e.get("speaker"), "text": e["text"]}], ctx)[0]
        over = v["label"] == "player_overreach"
        out.append({"facts": [f for f, rx in FACT_PATTERNS.items() if rx.search(e["text"])], "overreach": over,
                    "contradiction": False, **({"overreach_span": [[0, len(e["text"])]]} if over else {})})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    splits = load_splits(a.data)
    evaluate("m3_rung0_rule", splits, predict, a.out,
             {"rung": 0, "method": "the game's rule guard: FACT_PATTERNS regexes + player-input overlap; no contradictions",
              "n_train": 0})


if __name__ == "__main__":
    main()
