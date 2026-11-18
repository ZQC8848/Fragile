"""Metrics shared by every task 2 system. Standard library only.

score_system(examples, predictions) compares a system's turn-level predictions with the teacher targets
(or later with gold labels) on each head, with the right mask per head, and returns a JSON-able dict.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from typing import Any, Callable

from .data import HEADS_MULTI, HEADS_SINGLE, char_tags, head_mask, targets


def f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if p + r else 0.0


def single_label_report(y_true: list[str], y_pred: list[str], min_support: int = 20) -> dict[str, Any]:
    labels = sorted(set(y_true))
    tp, fp, fn = Counter(), Counter(), Counter()
    for t, p in zip(y_true, y_pred):
        if t == p:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1
    per = {}
    for c in labels:
        prec = tp[c] / (tp[c] + fp[c]) if tp[c] + fp[c] else 0.0
        rec = tp[c] / (tp[c] + fn[c]) if tp[c] + fn[c] else 0.0
        per[c] = {"p": prec, "r": rec, "f1": f1(prec, rec), "support": tp[c] + fn[c]}
    big = [v["f1"] for v in per.values() if v["support"] >= min_support]
    return {
        "n": len(y_true),
        "accuracy": sum(t == p for t, p in zip(y_true, y_pred)) / len(y_true) if y_true else 0.0,
        "macro_f1": sum(v["f1"] for v in per.values()) / len(per) if per else 0.0,  # mean of per-class F1
        f"macro_f1_support{min_support}": sum(big) / len(big) if big else None,
        "per_class": per,
    }


def multi_label_report(y_true: list[list[str]], y_pred: list[list[str]], labels: list[str]) -> dict[str, Any]:
    tp, fp, fn = Counter(), Counter(), Counter()
    exact = 0
    for t, p in zip(y_true, y_pred):
        ts, ps = set(t), set(p)
        exact += ts == ps
        for c in ts & ps:
            tp[c] += 1
        for c in ps - ts:
            fp[c] += 1
        for c in ts - ps:
            fn[c] += 1
    TP, FP, FN = sum(tp.values()), sum(fp.values()), sum(fn.values())
    micro = f1(TP / (TP + FP) if TP + FP else 0.0, TP / (TP + FN) if TP + FN else 0.0)
    present = [c for c in labels if tp[c] + fn[c] > 0]
    per = {}
    for c in present:
        prec = tp[c] / (tp[c] + fp[c]) if tp[c] + fp[c] else 0.0
        rec = tp[c] / (tp[c] + fn[c]) if tp[c] + fn[c] else 0.0
        per[c] = {"p": prec, "r": rec, "f1": f1(prec, rec), "support": tp[c] + fn[c]}
    return {
        "n": len(y_true),
        "micro_f1": micro,
        "macro_f1": sum(v["f1"] for v in per.values()) / len(per) if per else 0.0,  # mean of per-class F1 over present classes
        "exact_match": exact / len(y_true) if y_true else 0.0,
        "per_class": per,
    }


def regression_report(y_true: list[float], y_pred: list[float]) -> dict[str, Any]:
    n = len(y_true)
    mae = sum(abs(a - b) for a, b in zip(y_true, y_pred)) / n if n else 0.0
    return {"n": n, "mae": mae, "qwk": qwk([round(x) for x in y_true], [round(min(3, max(0, x))) for x in y_pred])}


def qwk(a: list[int], b: list[int], k: int = 4) -> float:
    """Quadratic-weighted Cohen's kappa for ordinal labels 0..k-1."""
    if not a:
        return 0.0
    O = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        O[x][y] += 1
    n = len(a)
    ha, hb = Counter(a), Counter(b)
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = (i - j) ** 2 / (k - 1) ** 2
            num += w * O[i][j]
            den += w * ha[i] * hb[j] / n
    return 1 - num / den if den else 1.0


def seg_report(texts: list[str], gold: list[list[str]], pred: list[list[str]]) -> dict[str, Any]:
    """Per-character micro F1 over S/A/E (whitespace skipped), plus per-channel F1."""
    tp, fp, fn = Counter(), Counter(), Counter()
    for text, g, p in zip(texts, gold, pred):
        for ch, gt, pt in zip(text, g, p):
            if ch.isspace():
                continue
            if gt == pt and gt != "O":
                tp[gt] += 1
            else:
                if pt != "O":
                    fp[pt] += 1
                if gt != "O":
                    fn[gt] += 1
    TP, FP, FN = sum(tp.values()), sum(fp.values()), sum(fn.values())
    per = {c: f1(tp[c] / (tp[c] + fp[c]) if tp[c] + fp[c] else 0.0, tp[c] / (tp[c] + fn[c]) if tp[c] + fn[c] else 0.0) for c in "SAE"}
    return {"n": len(texts), "char_f1": f1(TP / (TP + FP) if TP + FP else 0.0, TP / (TP + FN) if TP + FN else 0.0), "per_channel_f1": per}


def bootstrap(values: list[Any], stat: Callable[[list[Any]], float], n: int = 1000, seed: int = 0) -> tuple[float, float]:
    """95% percentile interval of `stat` over resamples of `values`."""
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    stats = sorted(stat([values[rng.randrange(len(values))] for _ in values]) for _ in range(n))
    return stats[int(0.025 * n)], stats[int(0.975 * n) - 1]


def score_system(examples: list[dict[str, Any]], preds: list[dict[str, Any]], seg_preds: list[list[str]] | None = None,
                 ci: bool = True) -> dict[str, Any]:
    """Score turn-level predictions against the examples' (teacher) targets, head by head."""
    out: dict[str, Any] = {"n": len(examples)}
    golds = [targets(e) for e in examples]
    for head, labels in HEADS_MULTI.items():
        out[head] = multi_label_report([g[head] for g in golds], [p.get(head, []) for p in preds], labels)
    for head in HEADS_SINGLE:
        idx = [i for i, e in enumerate(examples) if head_mask(e, head)]
        yt = [golds[i][head] for i in idx]
        yp = [preds[i].get(head, "none") for i in idx]
        rep = single_label_report(yt, yp)
        if ci and yt:
            pairs = list(zip(yt, yp))
            rep["accuracy_ci95"] = bootstrap(pairs, lambda s: sum(a == b for a, b in s) / len(s))
        out[head] = rep
    out["suspicion"] = regression_report([g["suspicion"] for g in golds], [float(p.get("suspicion", 0.0)) for p in preds])
    if seg_preds is not None:
        idx = [i for i, e in enumerate(examples) if head_mask(e, "seg")]
        if idx:
            out["seg"] = seg_report([examples[i]["text"] for i in idx], [char_tags(examples[i]["text"], examples[i]["segments"]) for i in idx],
                                    [seg_preds[i] for i in idx])
    if ci:
        pairs = [(set(g["act_set"]), set(p.get("act_set", []))) for g, p in zip(golds, preds)]
        out["act_set"]["exact_ci95"] = bootstrap(pairs, lambda s: sum(a == b for a, b in s) / len(s))
    return out


def headline(m: dict[str, Any]) -> dict[str, Any]:
    """The few numbers that go in the comparison table."""
    row = {
        "act_set_microF1": m["act_set"]["micro_f1"], "act_set_macroF1": m["act_set"]["macro_f1"],
        "topics_microF1": m["topics"]["micro_f1"], "claims_microF1": m["claims"]["micro_f1"],
        "addressee_acc": m["addressee"]["accuracy"], "action_acc": m["action"]["accuracy"],
        "suspicion_MAE": m["suspicion"]["mae"], "suspicion_QWK": m["suspicion"]["qwk"],
        "nora_acc": m["nora"]["accuracy"] if m["nora"]["n"] else None, "side_acc": m["side"]["accuracy"] if m["side"]["n"] else None,
    }
    if "seg" in m:
        row["seg_charF1"] = m["seg"]["char_f1"]
    return row


def per_lang(examples: list[dict[str, Any]]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for i, e in enumerate(examples):
        groups[e["lang"]].append(i)
    return dict(groups)
