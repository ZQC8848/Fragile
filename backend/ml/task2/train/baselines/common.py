"""Shared plumbing for the baselines: load splits, score, write runs/<name>/metrics.json."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from ..data import load_jsonl
from ..metrics import headline, per_lang, score_system

EVAL_SPLITS = ("val", "test", "seeds")


def parse_args(name: str) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=f"task 2 baseline: {name}")
    ap.add_argument("--data", required=True, help="directory with train.jsonl, val.jsonl, test.jsonl (and optional seeds.jsonl)")
    ap.add_argument("--out", required=True, help="runs directory; writes <out>/<name>/metrics.json")
    ap.add_argument("--name", default=name)
    ap.add_argument("--seed", type=int, default=0)
    return ap.parse_args()


def load_splits(data: str) -> dict[str, list[dict[str, Any]]]:
    d = Path(data)
    out = {}
    for split in ("train", *EVAL_SPLITS):
        p = d / f"{split}.jsonl"
        if p.exists():
            out[split] = load_jsonl(p)
    return out


def evaluate(name: str, splits: dict[str, list[dict]], predict, out_dir: str, extra: dict | None = None) -> dict:
    """predict(examples) -> (turn_level_preds, seg_preds_or_None). Scores every eval split, overall and per language."""
    result: dict[str, Any] = {"system": name, "time": time.strftime("%Y-%m-%d %H:%M"), **(extra or {}), "splits": {}}
    for split in EVAL_SPLITS:
        if split not in splits:
            continue
        exs = splits[split]
        if not exs:
            continue
        preds, segs = predict(exs)
        full = score_system(exs, preds, segs)
        by_lang = {}
        for lang, idx in per_lang(exs).items():
            sub = [exs[i] for i in idx]
            by_lang[lang] = headline(score_system(sub, [preds[i] for i in idx], [segs[i] for i in idx] if segs else None, ci=False))
        result["splits"][split] = {"n": len(exs), "headline": headline(full), "by_lang": by_lang, "full": full}
    path = Path(out_dir) / name
    path.mkdir(parents=True, exist_ok=True)
    (path / "metrics.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=float), encoding="utf-8")
    for split, r in result["splits"].items():
        print(f"[{name}] {split} n={r['n']}: " + ", ".join(f"{k}={v:.3f}" for k, v in r["headline"].items() if isinstance(v, float)))
    return result
