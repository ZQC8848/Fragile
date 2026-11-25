"""Collect every number behind the task 2 final figures (M2 compliance + understanding, M3 narration guard) into
figures_data.json and embed it into figures.html (template: figures_template.html, placeholder /*FIGURE_DATA*/).

    python -m ml.task2.final.build_figures --runs ~/fragile_task2_handoff/runs --data ~/fragile_task2_data/m3/examples

Inputs are the run outputs in the handoff repo (metrics.json, preds_<split>.jsonl) and the M3 test examples; both live
outside this repo. Nothing is retrained: the only new computation is the passage-level threshold sweep and the
localisation counts, both from saved predictions.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import time
from collections import defaultdict
from pathlib import Path

from ..train.m3_data import compose, gold_label, load_splits

HERE = Path(__file__).parent
SWEEP = [round(0.05 * i, 2) for i in range(1, 20)]

M3_SYSTEMS = {  # run name -> (key, label shown on the figures)
    "m3_rung0_rule": ("rule", "Keyword rules"),
    "m3_llm_guard_deepseek": ("deepseek", "DeepSeek guard (LLM API)"),
    "m3_rung1_tfidf": ("tfidf", "TF-IDF + logistic regression"),
    "m3_r9_selfplay_only_ens": ("ours_selfplay", "Ours, self-play data only (3-seed ensemble)"),
    "m3_r9_ens": ("ours_main", "Ours, + rewrites + logged drafts (3-seed ensemble)"),
}


def _m(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _head(m: dict, split: str) -> dict:
    sp = m["splits"][split]
    return sp.get("headline_tuned") or sp["headline"]


def _detail(m: dict, split: str) -> dict:
    sp = m["splits"][split]
    return sp.get("detail_tuned") or sp["detail"]


def _preds(path: Path) -> dict[str, dict]:
    return {d["ex_id"]: d for d in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def passage_sweep(test: list[dict], preds: dict[str, dict]) -> list[dict]:
    """One threshold t for every head (facts, overreach, contradiction): passage false-reject and recall."""
    gold_turn: dict[str, bool] = defaultdict(bool)
    for e in test:
        gold_turn[e["turn_id"]] |= gold_label(e) != "consistent"
    out = []
    for t in SWEEP:
        pred_turn: dict[str, bool] = defaultdict(bool)
        for e in test:
            p = preds[e["ex_id"]]
            facts = [f for f, q in zip(_facts_order(), p["p_facts"]) if q >= t]
            pred_turn[e["turn_id"]] |= compose(e, facts, p["p_overreach"] >= t, p["p_contradiction"] >= t) != "consistent"
        neg = [k for k, g in gold_turn.items() if not g]
        pos = [k for k, g in gold_turn.items() if g]
        out.append({"threshold": t, "false_reject": sum(pred_turn[k] for k in neg) / len(neg),
                    "recall": sum(pred_turn[k] for k in pos) / len(pos)})
    return out


def _facts_order() -> tuple[str, ...]:
    from ..train.m3_data import FACTS
    return FACTS


def localisation(test: list[dict], preds: dict[str, dict], thr: dict[str, float]) -> dict:
    turns: dict[str, list] = defaultdict(list)
    for e in test:
        p = preds[e["ex_id"]]
        turns[e["turn_id"]].append((e, p, gold_label(e), compose(e, p["facts"], p["p_overreach"] >= thr["overreach"],
                                                                  p["p_contradiction"] >= thr["contradiction"])))
    both = hit = exact = tp = fp = fn = lab_ok = lab_n = fact_ok = fact_n = 0
    for rows in turns.values():
        g = {i for i, r in enumerate(rows) if r[2] != "consistent"}
        c = {i for i, r in enumerate(rows) if r[3] != "consistent"}
        if not (g and c):
            continue
        both += 1; hit += bool(g & c); exact += g == c
        tp += len(g & c); fp += len(c - g); fn += len(g - c)
        for i in g & c:
            e, p, gl, cl = rows[i]
            lab_n += 1; lab_ok += gl == cl
            if gl == cl == "premature_leak":
                fact_n += 1
                fact_ok += bool((set(e["labels"]["facts"]) - set(e["revealed"])) & (set(p["facts"]) - set(e["revealed"])))
    return {"turns_rejected_by_both": both, "at_least_one_right_segment": hit / both, "exactly_right_segments": exact / both,
            "segment_precision": tp / (tp + fp), "segment_recall": tp / (tp + fn), "label_right": lab_ok / lab_n,
            "leak_fact_right": fact_ok / fact_n, "n_leak_segments": fact_n}


def m3(runs: Path, data: Path) -> dict:
    splits = load_splits(data)
    test = splits["test"]
    out: dict = {"systems": [], "sweep": {}, "localisation": {}, "logged": [], "seeds": {}}
    for run, (key, label) in M3_SYSTEMS.items():
        m = _m(runs / run / "metrics.json")
        h, d = _head(m, "test"), _detail(m, "test")
        row = {"key": key, "label": label, "run": run, "thresholds": m.get("tuned_thresholds"),
               **{k: h.get(k) for k in ("facts_microF1", "facts_macroF1", "overreach_F1", "overreach_AP", "overreach_spanF1",
                                         "contradiction_F1", "contradiction_AP", "contradiction_spanF1", "verdict_macroF1",
                                         "verdict_false_alarm", "leak_recall", "passage_F1", "passage_false_reject")},
               "passage_recall": d["passage"]["recall"], "passage_precision": d["passage"]["precision"]}
        out["systems"].append(row)
        if "test_logged" in m["splits"]:
            hl = _head(m, "test_logged"); dl = _detail(m, "test_logged")
            out["logged"].append({"key": key, "label": label, "verdict_macroF1": hl["verdict_macroF1"],
                                  "overreach_recall": dl["overreach"]["recall"], "contradiction_recall": dl["contradiction"]["recall"],
                                  "leak_recall": hl["leak_recall"]})
        if key.startswith("ours"):
            p = _preds(runs / run / "preds_test.jsonl")
            out["sweep"][key] = passage_sweep(test, p)
            out["localisation"][key] = {**localisation(test, p, m["tuned_thresholds"]),
                                        "overreach_span_charF1": h["overreach_spanF1"], "contradiction_span_charF1": h["contradiction_spanF1"]}
    t = _m(runs / "m3_teacher_sonnet_vs_opus" / "metrics.json")
    th, td = t["splits"]["test_sample"]["headline"], t["splits"]["test_sample"]["detail"]
    out["teacher"] = {"label": "Second teacher (Claude Opus vs Sonnet, 150 test turns)", "n_segments": t["splits"]["test_sample"]["n"],
                      **{k: th.get(k) for k in ("facts_microF1", "overreach_F1", "contradiction_F1", "verdict_macroF1", "leak_recall",
                                                 "passage_F1", "passage_false_reject")},
                      "passage_recall": td["passage"]["recall"], "n_turns": td["passage"]["n"]}
    for group, members in (("ours_main", ["m3_r9_s0", "m3_r9_s1", "m3_r9_s2"]),
                           ("ours_selfplay", ["m3_r9_selfplay_only_s0", "m3_r9_selfplay_only_s1", "m3_r9_selfplay_only_s2"])):
        ens = "m3_r9_ens" if group == "ours_main" else "m3_r9_selfplay_only_ens"
        keys = ("facts_microF1", "overreach_AP", "contradiction_AP", "verdict_macroF1", "leak_recall", "passage_false_reject")
        out["seeds"][group] = {"seeds": [{k: _head(_m(runs / r / "metrics.json"), "test")[k] for k in keys} for r in members],
                               "ensemble": {k: _head(_m(runs / ens / "metrics.json"), "test")[k] for k in keys},
                               "thresholds": [_m(runs / r / "metrics.json")["tuned_thresholds"] for r in members + [ens]]}
    b8 = [_head(_m(runs / f"m3_rung4_s{i}" / "metrics.json"), "test") for i in range(3)]
    out["batch8_seed_mean"] = {k: st.mean(h[k] for h in b8) for k in ("facts_microF1", "overreach_AP", "contradiction_AP", "verdict_macroF1",
                                                                       "leak_recall", "passage_false_reject")}
    gold = defaultdict(int); turns = defaultdict(bool)
    for e in test:
        g = gold_label(e); gold[g] += 1; turns[e["turn_id"]] |= g != "consistent"
    out["test_stats"] = {"segments": len(test), "turns": len(turns), "turns_gold_rejected": sum(turns.values()), "gold_verdicts": dict(gold)}
    stats = {}
    for s, exs in splits.items():
        c = defaultdict(int)
        for e in exs:
            c[f"{e['source']}"] += 1
            c["overreach"] += e["labels"]["overreach"]; c["contradiction"] += e["labels"]["contradiction"]; c["states_a_fact"] += bool(e["labels"]["facts"])
        stats[s] = {"n": len(exs), **c}
    out["data_stats"] = stats
    return out


def m2(runs: Path) -> dict:
    seeds = [f"rung4_full_e30_s{i}" for i in range(3)]
    base = {"rung0_rule": "Keyword rules", "rung1_tfidf": "TF-IDF + logistic regression", "rung2_embed": "Frozen e5 embeddings + LR"}
    out: dict = {"compliance": {}, "understanding": []}
    for split in ("test", "seeds"):
        ms = [_m(runs / s / "metrics.json")["splits"][split]["full"]["validity_binary"] for s in seeds]
        curve = [{"threshold": c[0]["threshold"], "false_reject": st.mean(x["false_reject"] for x in c), "miss": st.mean(x["miss"] for x in c)}
                 for c in zip(*(m["curve"] for m in ms))]
        pts = [{"key": k, "label": lab, "false_reject": vb["false_reject"], "miss": vb["miss"]}
               for k, lab in base.items() for vb in [_m(runs / k / "metrics.json")["splits"][split]["full"]["validity_binary"]]]
        out["compliance"][split] = {
            "n_ok": ms[0]["n_ok"], "n_violation": ms[0]["n_violation"], "curve_mean_of_3_seeds": curve,
            "ours": {"false_reject": st.mean(m["false_reject"] for m in ms), "miss": st.mean(m["miss"] for m in ms),
                     "auroc": st.mean(m["auroc"] for m in ms), "category_acc_on_violations": st.mean(m["category_acc_on_violations"] for m in ms)},
            "baselines": pts}
    keys = [("act_set_microF1", "Dialogue acts (micro-F1)"), ("topics_microF1", "Topics (micro-F1)"), ("claims_microF1", "Claims (micro-F1)"),
            ("addressee_acc", "Addressee (accuracy)"), ("suspicion_QWK", "Suspicion (QWK)"), ("nora_acc", "Nora truth/lie (accuracy)"),
            ("seg_charF1", "Segmentation (char-F1)"), ("validity_auroc", "Compliance (AUROC)")]
    rows = {k: _m(runs / k / "metrics.json")["splits"]["test"]["headline"] for k in base}
    ours = [_m(runs / s / "metrics.json")["splits"]["test"]["headline"] for s in seeds]
    for k, lab in keys:
        out["understanding"].append({"metric": k, "label": lab, **{b: rows[b].get(k) for b in base},
                                     "ours": st.mean(h[k] for h in ours), "ours_seeds": [h[k] for h in ours]})
    out["understanding_systems"] = {**base, "ours": "Ours, mDeBERTa multi-head (3 seeds, mean)"}
    out["test_n"] = _m(runs / seeds[0] / "metrics.json")["splits"]["test"]["n"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="the handoff repo's runs/ directory")
    ap.add_argument("--data", required=True, help="M3 examples directory")
    a = ap.parse_args()
    runs = Path(a.runs).expanduser()
    data = {"generated": time.strftime("%Y-%m-%d"), "m3": m3(runs / "m3", Path(a.data).expanduser()), "m2": m2(runs / "v3")}
    (HERE / "figures_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tpl = (HERE / "figures_template.html").read_text(encoding="utf-8")
    (HERE / "figures.html").write_text(tpl.replace("/*FIGURE_DATA*/", json.dumps(data, ensure_ascii=False)), encoding="utf-8")
    print("wrote figures_data.json and figures.html")


if __name__ == "__main__":
    main()
