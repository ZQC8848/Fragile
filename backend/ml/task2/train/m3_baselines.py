"""M3 baselines that need no engine: majority (nothing is ever flagged) and TF-IDF + logistic regression.

TF-IDF features per head:
  facts          word 1-2-grams and char 2-5-grams of the segment (one-vs-rest, one classifier per fact)
  overreach      the segment, plus the player's input as a separate vocabulary, plus the segment kind
  contradiction  the segment, plus the scene summary and the previous passage as a separate vocabulary
Class weights are balanced (positives are rare). The rule baseline (the game's FACT_PATTERNS and player-input
overlap) imports the engine, so it lives in gen/m3_rule_baseline.py.

    python -m ml.task2.train.m3_baselines --data DATA --out RUNS [--which majority tfidf]
"""
from __future__ import annotations

import argparse

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from .m3_data import FACTS, heard_text, load_splits, player_text, scene_text, seg_text
from .m3_metrics import evaluate

KINDS = ["me", "me_speech", "narration", "speech"]


def _vec(word: bool = True) -> TfidfVectorizer:
    if word:
        return TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=50000)
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, sublinear_tf=True, max_features=80000)


class Feats:
    def __init__(self, parts):
        self.parts = parts  # [(extractor, vectorizer)]

    def fit(self, exs):
        for f, v in self.parts:
            v.fit([f(e) for e in exs])
        return self

    def __call__(self, exs):
        mats = [v.transform([f(e) for e in exs]) for f, v in self.parts]
        kind = csr_matrix(np.array([[float(e["kind"] == k) for k in KINDS] for e in exs]))
        return hstack(mats + [kind]).tocsr()


def tfidf(splits, seed: int = 0):
    train = splits["train"]
    seg = lambda e: seg_text(e)
    f_facts = Feats([(seg, _vec()), (seg, _vec(False))]).fit(train)
    f_over = Feats([(seg, _vec()), (seg, _vec(False)), (lambda e: player_text(e.get("player_input")), _vec())]).fit(train)
    f_con = Feats([(seg, _vec()), (seg, _vec(False)), (lambda e: " ".join([scene_text(e["scene"]), heard_text(e["scene"]), e.get("previous_passage") or ""]), _vec())]).fit(train)
    Xf = f_facts(train)
    fact_clf = {}
    for j, fact in enumerate(FACTS):
        y = np.array([fact in e["labels"]["facts"] for e in train], dtype=int)
        if 0 < y.sum() < len(y):
            fact_clf[fact] = LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000, random_state=seed).fit(Xf, y)
    bin_clf = {}
    for h, f in (("overreach", f_over), ("contradiction", f_con)):
        y = np.array([e["labels"][h] for e in train], dtype=int)
        bin_clf[h] = (f, LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000, random_state=seed).fit(f(train), y))

    def predict(exs):
        Xe = f_facts(exs)
        pf = {fact: c.predict_proba(Xe)[:, 1] for fact, c in fact_clf.items()}
        pb = {h: c.predict_proba(f(exs))[:, 1] for h, (f, c) in bin_clf.items()}
        return [{"facts": [fact for fact in FACTS if fact in pf and pf[fact][i] >= 0.5],
                 "p_overreach": float(pb["overreach"][i]), "p_contradiction": float(pb["contradiction"][i])}
                for i in range(len(exs))]
    return predict


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--which", nargs="+", default=["majority", "tfidf"], choices=["majority", "tfidf"])
    a = ap.parse_args()
    splits = load_splits(a.data)
    if "majority" in a.which:
        evaluate("m3_rung0_majority", splits, lambda exs: [{"facts": [], "overreach": False, "contradiction": False} for _ in exs],
                 a.out, {"rung": 0, "method": "nothing is ever flagged", "n_train": len(splits["train"])})
    if "tfidf" in a.which:
        evaluate("m3_rung1_tfidf", splits, tfidf(splits), a.out,
                 {"rung": 1, "method": "TF-IDF (word + char) + logistic regression, balanced, per head", "n_train": len(splits["train"])})


if __name__ == "__main__":
    main()
