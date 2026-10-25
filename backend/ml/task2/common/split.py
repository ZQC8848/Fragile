"""Train / val / test split by session, with near-duplicate control.

Splitting by session keeps a game's turns together, but the opening turns of different games repeat
("I smile and hand her my coat"), so val and test examples that nearly duplicate a train example are
dropped, and each near-duplicate cluster keeps at most `cap` examples. Rewrite examples (English text the
teacher wrote) only go to train, and at most `rewrite_frac` of it.

    python -m task2.common.split --examples examples/all.jsonl --out examples/   (on CARC)
    uv run python -m ml.task2.common.split ...                                   (locally)

Exits non-zero if any test or val example still nearly duplicates a train example.
Standard library only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

from .textnorm import normalize


def shingles(text: str, n: int = 5) -> set[str]:
    t = normalize(text).lower()
    if len(t) <= n:
        return {t} if t else set()
    return {t[i:i + n] for i in range(len(t) - n + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def session_split(session: str, seed: str = "task2", ratios: tuple[float, float] = (0.8, 0.1)) -> str:
    h = int(hashlib.sha1(f"{seed}:{session}".encode()).hexdigest(), 16) / 16**40
    if h < ratios[0]:
        return "train"
    return "val" if h < ratios[0] + ratios[1] else "test"


class NearDupIndex:
    """Inverted shingle index for fast near-duplicate lookup."""

    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold
        self.items: list[set[str]] = []
        self.index: dict[str, list[int]] = defaultdict(list)

    def add(self, sh: set[str]) -> int:
        i = len(self.items)
        self.items.append(sh)
        for s in sh:
            self.index[s].append(i)
        return i

    def neighbours(self, sh: set[str]) -> list[int]:
        counts: dict[int, int] = defaultdict(int)
        for s in sh:
            for i in self.index.get(s, ()):
                counts[i] += 1
        need = self.threshold * len(sh)
        return [i for i, c in counts.items() if c >= need * 0.5 and jaccard(sh, self.items[i]) >= self.threshold]


def split_examples(examples: list[dict], threshold: float = 0.9, cap: int = 3, rewrite_frac: float = 0.15) -> tuple[dict[str, list[dict]], dict]:
    buckets: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    for ex in examples:
        split = session_split(ex["session"])
        if ex.get("source") == "rewrite" and split != "train":
            continue
        buckets[split].append(ex)

    stats = {"input": len(examples), "dropped_cluster_cap": 0, "dropped_cross_split": 0, "dropped_rewrite_cap": 0}
    # cap near-duplicate clusters within train
    train_idx = NearDupIndex(threshold)
    cluster_size: dict[int, int] = defaultdict(int)
    kept_train: list[dict] = []
    for ex in buckets["train"]:
        sh = shingles(ex["text"])
        hits = train_idx.neighbours(sh)
        root = min(hits) if hits else None
        if root is not None and cluster_size[root] >= cap:
            stats["dropped_cluster_cap"] += 1
            continue
        i = train_idx.add(sh)
        cluster_size[root if root is not None else i] += 1
        kept_train.append(ex)
    # cap rewrites
    max_rw = int(rewrite_frac * len(kept_train))
    rw = [e for e in kept_train if e.get("source") == "rewrite"]
    if len(rw) > max_rw:
        drop = {id(e) for e in rw[max_rw:]}
        stats["dropped_rewrite_cap"] = len(drop)
        kept_train = [e for e in kept_train if id(e) not in drop]
    buckets["train"] = kept_train
    # drop val/test examples that nearly duplicate train
    final_idx = NearDupIndex(threshold)
    for ex in kept_train:
        final_idx.add(shingles(ex["text"]))
    for split in ("val", "test"):
        keep = []
        for ex in buckets[split]:
            if final_idx.neighbours(shingles(ex["text"])):
                stats["dropped_cross_split"] += 1
            else:
                keep.append(ex)
        buckets[split] = keep
    stats.update({f"n_{k}": len(v) for k, v in buckets.items()})
    return buckets, stats


def leaks(buckets: dict[str, list[dict]], threshold: float = 0.9) -> int:
    idx = NearDupIndex(threshold)
    for ex in buckets["train"]:
        idx.add(shingles(ex["text"]))
    sessions = {ex["session"] for ex in buckets["train"]}
    n = 0
    for split in ("val", "test"):
        for ex in buckets[split]:
            if ex["session"] in sessions or idx.neighbours(shingles(ex["text"])):
                n += 1
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=0.9)
    args = ap.parse_args()
    examples = [json.loads(line) for line in Path(args.examples).read_text(encoding="utf-8").splitlines() if line.strip()]
    buckets, stats = split_examples(examples, args.threshold)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in buckets.items():
        (out / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    n_leak = leaks(buckets, args.threshold)
    stats["leaks"] = n_leak
    print(json.dumps(stats, indent=1))
    sys.exit(1 if n_leak else 0)


if __name__ == "__main__":
    main()
