"""M3 scoring: the three perception heads against the Claude teacher, and the composed guard verdicts.

A system's prediction for one segment:
  {"facts": [...], "p_facts": [10 floats] | absent,
   "p_overreach": float | absent, "p_contradiction": float | absent  (or "overreach"/"contradiction": bool),
   "overreach_span": [[s, e], ...], "contradiction_span": [[s, e], ...]}   (spans optional)
Thresholds for the two binary heads are 0.5, and also chosen on val (best F1) and applied unchanged to the other
splits ("tuned"). Tuning uses only the val examples from real sources (selfplay and logged, REAL_SOURCES): the DeepSeek
rewrites are easier than real passages, and thresholds fitted to them do not carry over to the test set. Leaks are judged by recall, the other two by false alarms as well (backend-design.md §11: a guard
that blocks too much kills the scene).

    evaluate(name, splits, predict, out_dir, extra) -> writes <out_dir>/<name>/metrics.json
                                                       and <out_dir>/<name>/preds_<split>.jsonl (for ensembles and plots)
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

from .m3_data import BINARY, FACTS, LABELS, compose, find_span, gold_label
from .metrics import f1, multi_label_report, single_label_report

THRESHOLDS = [round(0.05 * i, 2) for i in range(1, 20)]
REAL_SOURCES = ("selfplay", "logged")


def auroc(y: list[int], s: list[float]) -> float | None:
    pos = [v for v, t in zip(s, y) if t]
    neg = [v for v, t in zip(s, y) if not t]
    if not pos or not neg:
        return None
    ranked = sorted(zip(s, y))
    # rank-sum with ties averaged
    ranks, i = {}, 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        for k in range(i, j):
            ranks[k] = (i + j + 1) / 2
        i = j
    r_pos = sum(ranks[k] for k, (_, t) in enumerate(ranked) if t)
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def average_precision(y: list[int], s: list[float]) -> float | None:
    n_pos = sum(y)
    if not n_pos:
        return None
    hits, ap = 0, 0.0
    for k, (_, t) in enumerate(sorted(zip(s, y), key=lambda x: -x[0]), 1):
        if t:
            hits += 1
            ap += hits / k
    return ap / n_pos


def binary_report(y: list[int], s: list[float], thr: float) -> dict[str, Any]:
    p = [int(v >= thr) for v in s]
    tp = sum(a and b for a, b in zip(y, p)); fp = sum(b and not a for a, b in zip(y, p)); fn = sum(a and not b for a, b in zip(y, p))
    neg = len(y) - sum(y)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"threshold": thr, "n_pos": sum(y), "precision": prec, "recall": rec, "f1": f1(prec, rec),
            "false_alarm": fp / neg if neg else 0.0, "flagged": sum(p)}


def best_threshold(y: list[int], s: list[float]) -> float:
    return max(THRESHOLDS, key=lambda t: (binary_report(y, s, t)["f1"], -abs(t - 0.5)))


def _score(pred: dict[str, Any], head: str) -> float:
    if f"p_{head}" in pred:
        return float(pred[f"p_{head}"])
    return 1.0 if pred.get(head) else 0.0


def span_f1(exs: list[dict[str, Any]], preds: list[dict[str, Any]], head: str) -> dict[str, Any] | None:
    tp = fp = fn = n = 0
    for e, p in zip(exs, preds):
        g = e["labels"].get(f"{head}_span") if e["labels"][head] else None
        if g is None or f"{head}_span" not in p:
            continue
        n += 1
        gold = {i for i in range(*g) if not e["text"][i].isspace()}
        got = {i for s, t in p[f"{head}_span"] for i in range(s, min(t, len(e["text"]))) if not e["text"][i].isspace()}
        tp += len(gold & got); fp += len(got - gold); fn += len(gold - got)
    if not n:
        return None
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"n": n, "char_p": prec, "char_r": rec, "char_f1": f1(prec, rec)}


def score(exs: list[dict[str, Any]], preds: list[dict[str, Any]], thr: dict[str, float] | None = None) -> dict[str, Any]:
    thr = thr or {h: 0.5 for h in BINARY}
    out: dict[str, Any] = {"n": len(exs), "thresholds": thr}
    out["facts"] = multi_label_report([e["labels"]["facts"] for e in exs], [p.get("facts", []) for p in preds], FACTS)
    flags = {}
    for h in BINARY:
        y = [int(e["labels"][h]) for e in exs]
        s = [_score(p, h) for p in preds]
        rep = binary_report(y, s, thr[h])
        if any(f"p_{h}" in p for p in preds):
            rep.update(auroc=auroc(y, s), ap=average_precision(y, s), curve=[binary_report(y, s, t) for t in THRESHOLDS])
        sp = span_f1(exs, preds, h)
        if sp:
            rep["span"] = sp
        out[h] = rep
        flags[h] = [v >= thr[h] for v in s]
    gold = [gold_label(e) for e in exs]
    comp = [compose(e, p.get("facts", []), flags["overreach"][i], flags["contradiction"][i]) for i, (e, p) in enumerate(zip(exs, preds))]
    out["verdict"] = single_label_report(gold, comp, min_support=5)
    cons = [i for i, g in enumerate(gold) if g == "consistent"]
    leaks = [i for i, g in enumerate(gold) if g == "premature_leak"]
    out["verdict"]["false_alarm"] = sum(comp[i] != "consistent" for i in cons) / len(cons) if cons else None
    out["verdict"]["leak_recall"] = sum(comp[i] == "premature_leak" for i in leaks) / len(leaks) if leaks else None
    out["verdict"]["confusion"] = {g: dict(Counter(c for gg, c in zip(gold, comp) if gg == g)) for g in LABELS}
    # passage level: the game sends a passage back if any segment fails
    turns: dict[str, list[bool]] = defaultdict(lambda: [False, False])
    for e, g, c in zip(exs, gold, comp):
        if e.get("source", "selfplay") != "selfplay":
            continue
        t = turns[e["turn_id"]]
        t[0] |= g != "consistent"; t[1] |= c != "consistent"
    if turns:
        tp = sum(a and b for a, b in turns.values()); fp = sum(b and not a for a, b in turns.values())
        fn = sum(a and not b for a, b in turns.values()); neg = sum(not a for a, _ in turns.values())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        out["passage"] = {"n": len(turns), "n_rejected_gold": tp + fn, "precision": prec, "recall": rec, "f1": f1(prec, rec),
                          "false_reject": fp / neg if neg else 0.0}
    return out


def headline(m: dict[str, Any]) -> dict[str, Any]:
    row = {"facts_microF1": m["facts"]["micro_f1"], "facts_macroF1": m["facts"]["macro_f1"]}
    for h in BINARY:
        r = m[h]
        row.update({f"{h}_P": r["precision"], f"{h}_R": r["recall"], f"{h}_F1": r["f1"], f"{h}_false_alarm": r["false_alarm"],
                    f"{h}_AP": r.get("ap"), f"{h}_AUROC": r.get("auroc"), f"{h}_spanF1": (r.get("span") or {}).get("char_f1")})
    v = m["verdict"]
    row.update({"verdict_macroF1": v["macro_f1"], "verdict_false_alarm": v["false_alarm"], "leak_recall": v["leak_recall"]})
    if "passage" in m:
        row.update({"passage_F1": m["passage"]["f1"], "passage_false_reject": m["passage"]["false_reject"]})
    return row


def by_source(exs, preds, thr) -> dict[str, Any]:
    groups = defaultdict(list)
    for i, e in enumerate(exs):
        groups[e.get("source", "selfplay")].append(i)
    if len(groups) < 2:
        return {}
    return {s: headline(score([exs[i] for i in ix], [preds[i] for i in ix], thr)) for s, ix in groups.items()}


def evaluate(name: str, splits: dict[str, list[dict[str, Any]]], predict: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
             out_dir: str | Path, extra: dict[str, Any] | None = None,
             tune_sources: tuple[str, ...] | None = REAL_SOURCES, save_preds: bool = True) -> dict[str, Any]:
    preds = {s: predict(exs) for s, exs in splits.items() if exs}
    tuned = None
    if "val" in preds and all(any(f"p_{h}" in p for p in preds["val"]) for h in BINARY):
        ix = [i for i, e in enumerate(splits["val"]) if tune_sources is None or e.get("source", "selfplay") in tune_sources]
        tuned = {h: best_threshold([int(splits["val"][i]["labels"][h]) for i in ix], [_score(preds["val"][i], h) for i in ix])
                 for h in BINARY}
    res = {"system": name, "time": time.strftime("%Y-%m-%d %H:%M:%S"), **(extra or {}), "tuned_thresholds": tuned,
           "tune_sources": list(tune_sources) if tune_sources else None, "splits": {}}
    d = Path(out_dir) / name
    d.mkdir(parents=True, exist_ok=True)
    for s, p in preds.items():
        m = score(splits[s], p)
        sp = {"n": len(p), "headline": headline(m), "detail": m, "by_source": by_source(splits[s], p, None)}
        if tuned:
            mt = score(splits[s], p, tuned)
            sp["headline_tuned"] = headline(mt)
            sp["detail_tuned"] = mt
        res["splits"][s] = sp
        hl = sp.get("headline_tuned") or sp["headline"]
        print(f"[{name}] {s} n={len(p)}: " + ", ".join(f"{k}={v:.3f}" for k, v in hl.items() if isinstance(v, float)), flush=True)
        if save_preds:
            with (d / f"preds_{s}.jsonl").open("w", encoding="utf-8") as f:
                for e, q in zip(splits[s], p):
                    f.write(json.dumps({"ex_id": e["ex_id"], **q}, ensure_ascii=False) + "\n")
    (d / "metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
