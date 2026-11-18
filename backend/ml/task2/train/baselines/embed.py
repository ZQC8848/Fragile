"""Rung 2: frozen multilingual sentence embeddings + logistic regression (course L4 representations, L7 transfer).

The encoder is not trained: player text and scene context are each mean-pooled into a vector by a pretrained
multilingual model, concatenated, and a linear classifier is fitted per head. Segmentation needs token-level
outputs, so it is not part of this rung.

    python -m task2.train.baselines.embed --data DATA/examples --out RUNS --model intfloat/multilingual-e5-base   (CARC, GPU)
"""

from __future__ import annotations

import argparse

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.multiclass import OneVsRestClassifier
from sklearn.preprocessing import MultiLabelBinarizer, StandardScaler
from transformers import AutoModel, AutoTokenizer

from ..data import HEADS_MULTI, HEADS_SINGLE, head_mask, targets
from .common import evaluate, load_splits


@torch.no_grad()
def embed(texts: list[str], tok, model, device, prefix: str, batch: int = 64) -> np.ndarray:
    out = []
    for i in range(0, len(texts), batch):
        enc = tok([prefix + t for t in texts[i:i + batch]], padding=True, truncation=True, max_length=256, return_tensors="pt").to(device)
        with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda" and torch.cuda.is_bf16_supported()):
            h = model(**enc).last_hidden_state
        m = enc["attention_mask"].unsqueeze(-1).to(h.dtype)
        v = (h * m).sum(1) / m.sum(1).clamp(min=1)
        out.append(torch.nn.functional.normalize(v.float(), dim=-1).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, model.config.hidden_size))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="intfloat/multilingual-e5-base")
    ap.add_argument("--prefix", default="query: ", help="e5 models expect 'query: '; use '' for others")
    ap.add_argument("--name", default="rung2_embed")
    args = ap.parse_args()
    splits = load_splits(args.data)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModel.from_pretrained(args.model).to(device).eval()

    def featurize(exs):
        a = embed([e["text"] for e in exs], tok, model, device, args.prefix)
        b = embed([e["context_text"] for e in exs], tok, model, device, args.prefix)
        return np.hstack([a, b])

    train = splits["train"]
    golds = [targets(e) for e in train]
    scaler = StandardScaler().fit(Xtr := featurize(train))
    X = scaler.transform(Xtr)
    models = {}
    for head, labels in HEADS_MULTI.items():
        mlb = MultiLabelBinarizer(classes=labels)
        Y = mlb.fit_transform([g[head] for g in golds])
        keep = Y.sum(0) > 0
        clf = OneVsRestClassifier(LogisticRegression(max_iter=3000, C=1.0, class_weight="balanced")).fit(X, Y[:, keep]) if keep.sum() else None
        models[head] = (mlb, keep, clf)
    for head in HEADS_SINGLE:
        idx = [i for i, e in enumerate(train) if head_mask(e, head)]
        ys = [golds[i][head] for i in idx]
        models[head] = ("const", ys[0] if ys else "none") if len(set(ys)) < 2 else (
            "clf", LogisticRegression(max_iter=3000, C=1.0, class_weight="balanced").fit(X[idx], ys))
    ridge = Ridge(alpha=10.0).fit(X, [g["suspicion"] for g in golds])

    def predict(exs):
        Xe = scaler.transform(featurize(exs))
        preds = [{} for _ in exs]
        for head in HEADS_MULTI:
            mlb, keep, clf = models[head]
            full = np.zeros((len(exs), len(mlb.classes_)), dtype=int)
            if clf is not None:
                full[:, keep] = clf.predict(Xe)
            for i, labs in enumerate(mlb.inverse_transform(full)):
                preds[i][head] = list(labs)
        for head in HEADS_SINGLE:
            kind, m = models[head]
            for i, y in enumerate([m] * len(exs) if kind == "const" else m.predict(Xe)):
                preds[i][head] = y
        for i, y in enumerate(ridge.predict(Xe)):
            preds[i]["suspicion"] = float(min(3.0, max(0.0, y)))
        return preds, None

    evaluate(args.name, splits, predict, args.out, {"rung": 2, "method": f"frozen {args.model} mean-pooled, + logistic regression", "n_train": len(train)})


if __name__ == "__main__":
    main()
