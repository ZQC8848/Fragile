"""Rung 1: TF-IDF features + logistic regression, one model per head (course L1 linear classifiers, L2 metrics).

Turn heads: character n-grams of the player text (works for Chinese without a word segmenter) plus word
n-grams of the scene context; multi-label heads use one-vs-rest; suspicion uses ridge regression.
Segmentation: per-character logistic regression on a window of surrounding characters and quote parity.

    python -m task2.train.baselines.tfidf --data DATA/examples --out RUNS        (CARC, CPU)
"""

from __future__ import annotations

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer

from ..data import HEADS_MULTI, HEADS_SINGLE, char_tags, head_mask, targets
from .common import evaluate, load_splits, parse_args

QUOTES = set("\"'“”‘’「」")


class TurnFeatures:
    def __init__(self):
        self.text = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 4), min_df=2, sublinear_tf=True)
        self.ctx = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, token_pattern=r"[^\s;|,=:]+")

    def fit(self, exs):
        self.text.fit([e["text"] for e in exs])
        self.ctx.fit([e["context_text"] for e in exs])
        return self

    def __call__(self, exs):
        return hstack([self.text.transform([e["text"] for e in exs]), self.ctx.transform([e["context_text"] for e in exs])]).tocsr()


def char_features(text: str) -> list[dict]:
    feats, inside = [], False
    for i, ch in enumerate(text):
        f = {"c0": ch, "inq": inside, "pos": min(i, 20), "rpos": min(len(text) - i, 20)}
        for k in (-3, -2, -1, 1, 2, 3):
            j = i + k
            f[f"c{k}"] = text[j] if 0 <= j < len(text) else "<pad>"
        f["bi-"] = text[max(0, i - 1):i + 1]
        f["bi+"] = text[i:i + 2]
        feats.append(f)
        if ch in QUOTES:
            inside = not inside
    return feats


def main() -> None:
    args = parse_args("rung1_tfidf")
    splits = load_splits(args.data)
    train = splits["train"]
    golds = [targets(e) for e in train]
    feats = TurnFeatures().fit(train)
    X = feats(train)
    models = {}
    for head, labels in HEADS_MULTI.items():
        mlb = MultiLabelBinarizer(classes=labels)
        Y = mlb.fit_transform([g[head] for g in golds])
        keep = Y.sum(0) > 0
        clf = None
        if keep.sum() > 0:
            clf = OneVsRestClassifier(LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced"))
            clf.fit(X, Y[:, keep])
        models[head] = (mlb, keep, clf)
    for head in HEADS_SINGLE:
        idx = [i for i, e in enumerate(train) if head_mask(e, head)]
        ys = [golds[i][head] for i in idx]
        if len(set(ys)) < 2:
            models[head] = ("const", ys[0] if ys else "none")
            continue
        clf = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced")
        clf.fit(X[idx], ys)
        models[head] = ("clf", clf)
    ridge = Ridge(alpha=1.0).fit(X, [g["suspicion"] for g in golds])
    seg_train = [e for e in train if head_mask(e, "seg")]
    dv, seg_clf = DictVectorizer(), None
    if seg_train:
        Xc = dv.fit_transform([f for e in seg_train for f in char_features(e["text"])])
        yc = [t for e in seg_train for t in char_tags(e["text"], e["segments"])]
        seg_clf = LogisticRegression(max_iter=3000, C=2.0).fit(Xc, yc)

    def predict(exs):
        Xe = feats(exs)
        preds = [{} for _ in exs]
        for head, (mlb, keep, clf) in ((h, models[h]) for h in HEADS_MULTI):
            full = np.zeros((len(exs), len(mlb.classes_)), dtype=int)
            if clf is not None:
                full[:, keep] = clf.predict(Xe)
            for i, labs in enumerate(mlb.inverse_transform(full)):
                preds[i][head] = list(labs)
        for head in HEADS_SINGLE:
            kind, m = models[head]
            ys = [m] * len(exs) if kind == "const" else m.predict(Xe)
            for i, y in enumerate(ys):
                preds[i][head] = y
        for i, y in enumerate(ridge.predict(Xe)):
            preds[i]["suspicion"] = float(min(3.0, max(0.0, y)))
        if seg_clf is None:
            return preds, None
        segs = []
        for e in exs:
            if not e["text"]:
                segs.append([])
                continue
            segs.append(list(seg_clf.predict(dv.transform(char_features(e["text"])))))
        return preds, segs

    evaluate(args.name, splits, predict, args.out, {"rung": 1, "method": "char/word TF-IDF + logistic regression; per-char LR segmentation",
                                                     "n_train": len(train)})


if __name__ == "__main__":
    main()
