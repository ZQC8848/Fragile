"""M3 LLM baseline: the game's own LLM guard path (prompts/guard_v1.md, role guard = DeepSeek) on the test turns.

Each test passage goes through LLMGuardPath.check with the context the logs allow: allowed = facts revealed by the
end of the turn (the same stand-in the composition rule uses), no speaker_allowed, the player's input, the scene,
opening / ending. Its one label per segment is read back as perceptions (leak -> its fact, overreach, contradiction),
so the composed verdicts compare like for like; per-head scores understate it where one label hides another.

    uv run python -m ml.task2.gen.m3_llm_baseline --data DATA --out RUNS [--slots 8]
Caches replies in $TASK2_DATA/m3/llm_guard_<model>.jsonl (resumable).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import defaultdict
from pathlib import Path

from engine.llm import load_env

from ..train.m3_data import load_splits
from ..train.m3_metrics import evaluate

DATA = Path(os.environ.get("TASK2_DATA", Path.home() / "fragile_task2_data"))


async def run(turns: list[dict], cache: Path, slots: int) -> None:
    from engine.models.guard import GuardContext, LLMGuardPath

    path, sem, lock = LLMGuardPath(), asyncio.Semaphore(slots), asyncio.Lock()

    async def one(t):
        ctx = GuardContext(allowed=set(t["revealed"]), player=t["player_input"] or {}, ending=t["ending"],
                           opening=t["opening"], scene={k: v for k, v in t["scene"].items()})
        segs = [{"kind": s["kind"], "speaker": s["speaker"], "text": s["text"]} for s in t["segments"]]
        async with sem:
            res = await path.check(segs, ctx)
        async with lock:
            with cache.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"id": t["id"], "verdicts": res["verdicts"], "fallback": res["fallback"],
                                    "model": (res["meta"] or {}).get("model")}, ensure_ascii=False) + "\n")

    await asyncio.gather(*(one(t) for t in turns))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--slots", type=int, default=8)
    ap.add_argument("--name", default="m3_llm_guard_deepseek")
    a = ap.parse_args()
    test = load_splits(a.data)["test"]
    rows = {r["id"]: r for r in map(json.loads, (DATA / "m3" / "turns.jsonl").read_text(encoding="utf-8").splitlines())}
    ids = sorted({e["turn_id"] for e in test})
    cache = DATA / "m3" / f"{a.name}.jsonl"
    done = {json.loads(l)["id"] for l in cache.read_text(encoding="utf-8").splitlines()} if cache.exists() else set()
    todo = [rows[i] for i in ids if i not in done]
    print(f"{len(todo)} test passages to check ({len(done)} cached)", flush=True)
    if todo:
        load_env()
        os.environ["LLM_LIVE_ROLES"] = "guard"
        os.environ["LLM_CACHE"] = "0"
        asyncio.run(run(todo, cache, a.slots))
    got = {d["id"]: d for d in map(json.loads, cache.read_text(encoding="utf-8").splitlines())}
    fallbacks = sum(d["fallback"] for d in got.values())
    verdict = defaultdict(dict)
    for d in got.values():
        for v in d["verdicts"]:
            verdict[d["id"]][v["index"]] = v

    def predict(exs):
        out = []
        for e in exs:
            v = verdict.get(e["turn_id"], {}).get(e["index"]) or {"label": "consistent"}
            lab = v["label"]
            out.append({"facts": [v["fact"]] if lab == "premature_leak" and v.get("fact") else [],
                        "overreach": lab == "player_overreach", "contradiction": lab == "contradiction"})
        return out

    evaluate(a.name, {"test": test}, predict, a.out,
             {"rung": "llm", "method": f"the game's LLM guard path (guard_v1, {next(iter(got.values()))['model'] if got else '?'}), "
                                      f"allowed = revealed by end of turn", "n_train": 0, "fallbacks": fallbacks})


if __name__ == "__main__":
    main()
