"""examples_v3 = examples_v2 with `nora_answer` relabelled by the review v2 rule (relabel_nora_v2.py, Claude).

Everything else is unchanged, including the splits and test_v1, so batch 7 stays comparable with batch 5.
Turns whose relabel is missing keep the v1 label and are counted.

    uv run python -m ml.task2.gen.build_examples_v3
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

DATA = Path(os.environ.get("TASK2_DATA", Path.home() / "fragile_task2_data"))


def main() -> int:
    lab = {}
    for line in (DATA / "relabel" / "nora_v2.jsonl").read_text(encoding="utf-8").splitlines():
        for it in json.loads(line)["data"]["items"]:
            lab[it["id"]] = it["nora_answer"]
    src, dst = DATA / "examples_v2", DATA / "examples_v3"
    dst.mkdir(exist_ok=True)
    for p in sorted(src.glob("*.jsonl")):
        out, stats = [], Counter()
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            v1 = r["turn_labels"].get("nora_answer")
            if v1 is not None:
                v2 = lab.get(r["ex_id"])
                if v2 is None:
                    stats["missing"] += 1
                else:
                    stats["same" if v2 == v1 else "changed"] += 1
                    r["turn_labels"]["nora_answer"] = v2
                    r.setdefault("relabels", {})["nora_answer"] = {"v1": v1, "source": "review_v2 rule, claude sonnet"}
            out.append(json.dumps(r, ensure_ascii=False))
        (dst / p.name).write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"{p.name}: {len(out)} examples, nora {dict(stats)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
