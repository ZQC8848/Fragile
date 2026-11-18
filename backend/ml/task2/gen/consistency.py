"""Teacher self-consistency: re-label a sample of inputs twice at temperature 0.7 and measure agreement.

Agreement between teacher samples is the ceiling a student trained on teacher labels can be expected to
reach on each head, and it flags heads whose labels are too unstable to trust.

    uv run python -m ml.task2.gen.consistency --run b1 --n 300
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
from collections import defaultdict

from engine.llm import load_env

from .relabel_tagged import rec_id
from .run_selfplay import DATA_ROOT


def heads(d: dict) -> dict:
    units = d.get("units") or []
    return {
        "validity": (d.get("validity") or {}).get("label"),
        "addressee": (d.get("channels") or {}).get("addressee"),
        "acts": tuple(u.get("act") for u in units),
        "first_act": units[0].get("act") if units else None,
        "topics": tuple(sorted({t for u in units for t in (u.get("topics") or [])})),
        "action": next((f"{u['action']['verb']}:{u['action']['target']}" for u in units if u.get("action")), None),
        "suspicion": d.get("suspicion"),
        "claims": tuple(sorted(d.get("claims") or [])),
        "nora_answer": d.get("nora_answer"),
        "side_answer": d.get("side_answer"),
        "n_units": len(units),
    }


async def run(args) -> None:
    from app.session import Session

    rows = [json.loads(x) for x in (DATA_ROOT / "raw" / args.run / "turns.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if r["teacher"] and r["input"] and r["attempt"] == 0]
    random.Random(0).shuffle(rows)
    rows = rows[: args.n]
    s = Session("consistency", None, save_generated=False)  # only to reach the encoder's review client and prompt
    enc = s.encoder.paths["llm"]
    sem = asyncio.Semaphore(args.slots)
    out = DATA_ROOT / "relabel" / f"{args.run}.consistency.jsonl"

    async def sample(r):
        payload = {"input": r["input"], "context": r["context"]}
        user = "Review this turn of player input. Return only the JSON object.\n\n" + f"```json\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n```"
        from engine.models.encoder import REVIEW_SCHEMA
        from engine.models.prompts import system_prompt

        prompt = system_prompt("review", ACTION_TABLE=enc.action_table)
        outs = []
        for _ in range(2):
            async with sem:
                try:
                    res = await enc.client.call_json(prompt.text, user, schema=REVIEW_SCHEMA, prompt_version=prompt.version, temperature=0.7)
                    outs.append(res.data)
                except Exception:
                    outs.append(None)
        return {"id": rec_id(r), "lang": r["lang"], "samples": [r["teacher"]["data"], *outs]}

    results = await asyncio.gather(*(sample(r) for r in rows))
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in results), encoding="utf-8")
    agree, total = defaultdict(int), defaultdict(int)
    for x in results:
        hs = [heads(d) for d in x["samples"] if d]
        if len(hs) < 2:
            continue
        for k in hs[0]:
            for h in hs[1:]:
                total[k] += 1
                agree[k] += h[k] == hs[0][k]
    print(f"teacher self-agreement on {len(results)} inputs (sample 0 = original label at T=0 vs two T=0.7 samples):")
    for k in total:
        print(f"  {k:12s} {agree[k] / total[k]:.0%}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--slots", type=int, default=6)
    args = ap.parse_args()
    load_env()
    os.environ["LLM_LIVE_ROLES"] = "review"
    os.environ["LLM_CACHE"] = "0"
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
