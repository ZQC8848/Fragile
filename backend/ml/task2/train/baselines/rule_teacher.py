"""Rung 0: the engine's keyword rules, and a majority-class floor, scored against the teacher labels.

The rule outputs were computed during generation (raw record field `rule`, copied into each example), so this
runs without the engine. Rule segmentation comes from its quote-based channels, located in the original text.

    python -m task2.train.baselines.rule_teacher --data DATA/examples --out RUNS       (CARC)
"""

from __future__ import annotations

from collections import Counter

from ...common.align import fuzzy_find
from ..data import HEADS_MULTI, HEADS_SINGLE, char_tags, targets, targets_from_review
from .common import evaluate, load_splits, parse_args


def rule_predict(exs):
    preds, segs = [], []
    for e in exs:
        rule = e.get("rule") or {}
        preds.append(targets_from_review(rule))
        spans = []
        ch = rule.get("channels") or {}
        if e["mode"] == "single":
            for name in ("speech", "action", "expression"):
                if ch.get(name):
                    hit = fuzzy_find(e["text"], ch[name], threshold=0.9)
                    if hit:
                        spans.append({"channel": name, "start": hit[0], "end": hit[1]})
        segs.append(char_tags(e["text"], spans))
    return preds, segs


def majority_predict(train):
    golds = [targets(e) for e in train]
    maj_single = {h: Counter(g[h] for g in golds).most_common(1)[0][0] for h in HEADS_SINGLE}
    maj_multi = {h: [l for l, c in Counter(x for g in golds for x in g[h]).items() if c > len(golds) / 2] for h in HEADS_MULTI}
    susp = sum(g["suspicion"] for g in golds) / len(golds)

    def predict(exs):
        preds = [{**maj_multi, **maj_single, "suspicion": susp} for _ in exs]
        segs = [["S" if not ch.isspace() else "O" for ch in e["text"]] for e in exs]  # everything is speech
        return preds, segs

    return predict


def main() -> None:
    args = parse_args("rung0")
    splits = load_splits(args.data)
    evaluate("rung0_rule", splits, rule_predict, args.out, {"rung": 0, "method": "engine RuleEncoder (keywords, quote split)"})
    evaluate("rung0_majority", splits, majority_predict(splits["train"]), args.out, {"rung": 0, "method": "majority class / all-speech floor"})


if __name__ == "__main__":
    main()
