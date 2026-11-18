"""Train / val / test split by session, with near-duplicate control.

Splitting by session keeps a game's turns together, but the opening turns of different games repeat
("I smile and hand her my coat"), so val and test examples that nearly duplicate a train example are
dropped, and each near-duplicate cluster keeps at most `cap` examples. Rewrite examples (English text the
teacher wrote) only go to train, and at most `rewrite_frac` of it.

    python -m task2.common.split --examples examples/all.jsonl --out examples/   (on CARC)
    uv run python -m ml.task2.common.split ...                                   (locally)

When the data grows, --pin OLD_DIR keeps every session of an earlier split where it was and splits only
the new sessions; OLD_DIR/test.jsonl is also copied verbatim to test_v1.jsonl, a frozen benchmark that
results from before the growth can be compared on.

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


def assign_sessions(examples: list[dict], ratios: tuple[float, float] = (0.8, 0.1), seed: str = "task2",
                    pinned: dict[str, str] | None = None) -> dict[str, str]:
    """Sessions ordered by a seeded hash, then cut so train/val/test hold ~80/10/10% of the examples.

    With only tens of games, assigning each session independently at random gives very uneven splits;
    cutting the hash-ordered list by example count keeps the proportions while staying deterministic.
    Rewrite examples are not counted, since they can only go to train. Sessions in `pinned` keep their split
    and the cut is made over the remaining sessions only. The cut is made separately per game language
    (a session's `lang`), since only ~10% of games are Chinese and an unstratified cut can leave val without any.
    """
    pinned = pinned or {}
    counts: dict[str, int] = defaultdict(int)
    stratum: dict[str, str] = {}
    for ex in examples:
        if ex.get("source") != "rewrite" and ex["session"] not in pinned:
            counts[ex["session"]] += 1
            stratum.setdefault(ex["session"], ex.get("lang", ""))
    out = dict(pinned)
    for lang in sorted(set(stratum.values())):
        group = [s for s in counts if stratum[s] == lang]
        order = sorted(group, key=lambda s: hashlib.sha1(f"{seed}:{s}".encode()).hexdigest())
        total, acc = sum(counts[s] for s in group), 0
        for s in order:
            frac = acc / total if total else 0.0
            out[s] = "train" if frac < ratios[0] else "val" if frac < ratios[0] + ratios[1] else "test"
            acc += counts[s]
    for ex in examples:
        out.setdefault(ex["session"], "train")
    return out


def split_examples(examples: list[dict], threshold: float = 0.9, cap: int = 3, rewrite_frac: float = 0.15,
                   pinned: dict[str, str] | None = None) -> tuple[dict[str, list[dict]], dict]:
    buckets: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    assignment = assign_sessions(examples, pinned=pinned)
    for ex in examples:
        split = assignment[ex["session"]]
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


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pinned_sessions(old_dir: Path) -> dict[str, str]:
    """Session -> split of an earlier split directory."""
    pinned: dict[str, str] = {}
    for split in ("train", "val", "test"):
        for ex in load_jsonl(old_dir / f"{split}.jsonl"):
            pinned[ex["session"]] = split
    return pinned


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=0.9)
    ap.add_argument("--pin", help="earlier split directory: its sessions keep their split, its test becomes test_v1")
    args = ap.parse_args()
    examples = load_jsonl(Path(args.examples))
    pinned = pinned_sessions(Path(args.pin)) if args.pin else None
    old_test = load_jsonl(Path(args.pin) / "test.jsonl") if args.pin else None
    buckets, stats = split_examples(examples, args.threshold, pinned=pinned)
    out = Path(args.out)
    if args.pin and out.resolve() == Path(args.pin).resolve():
        sys.exit("--out must differ from --pin")
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in buckets.items():
        (out / f"{name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    n_leak = leaks(buckets, args.threshold)
    stats["leaks"] = n_leak
    if old_test is not None:
        (out / "test_v1.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in old_test), encoding="utf-8")
        stats["pinned_sessions"] = len(pinned)
        stats["n_test_v1"] = len(old_test)
        # informational: test_v1 is frozen, so new train examples may come to nearly duplicate some of it
        stats["test_v1_near_dup_of_train"] = leaks({"train": buckets["train"], "val": [], "test": old_test}, args.threshold)
    print(json.dumps(stats, indent=1))
    sys.exit(1 if n_leak else 0)


if __name__ == "__main__":
    main()
