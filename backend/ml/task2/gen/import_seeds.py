"""Import the small real-source sets and label them with the teacher, in the same raw-record format.

  sonnet_en   the 32 player inputs of the lead's Sonnet playthrough (project/sonnet_playthrough.md)
  sonnet_zh   the same 32 inputs in the lead's Chinese translation (project/sonnet_playthrough.zh.md):
              a parallel set for checking that the teacher and the student treat both languages alike
  evals       backend/prompts/evals/review.jsonl (39 hand-written items, mostly validity checks, with context)

The Sonnet inputs were saved without their scene context, so an approximate one is used (living room, both
hosts present, phase by position in the game); treat results on them as a sanity check, not a benchmark.

    uv run python -m ml.task2.gen.import_seeds
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path

from engine.llm import load_env
from engine.paths import BACKEND_DIR, REPO_ROOT

from ..common.labels import SCHEMA_VERSION
from .run_selfplay import DATA_ROOT

PROJECT = REPO_ROOT.parent  # CSCI566/project, where the lead's playthrough files were saved
_INPUT = re.compile(r"^\*\*输入：\*\*\s*(.+)$")


def sonnet_inputs(path: Path) -> list[str]:
    return [m.group(1).strip() for line in path.read_text(encoding="utf-8").splitlines() if (m := _INPUT.match(line))]


def approx_context(i: int, n: int) -> dict:
    phase = "early" if i < n * 0.3 else "mid" if i < n * 0.65 else "late"
    return {"player_room": "living", "present": ["julian", "mia"], "on_call_with_nora": False, "phone_ringing": False,
            "story_phase": phase, "asking": None, "recent_npc_lines": []}


async def main_async() -> None:
    from app.session import Session

    s = Session("seeds", None, save_generated=False)
    await s.start("Sam", "female")
    items: list[tuple[str, int, dict, dict, dict | None]] = []
    for name, fname in (("sonnet_en", "sonnet_playthrough.md"), ("sonnet_zh", "sonnet_playthrough.zh.md")):
        texts = sonnet_inputs(PROJECT / fname)
        for i, t in enumerate(texts):
            items.append((name, i + 1, {"mode": "single", "text": t}, approx_context(i, len(texts)), None))
    for i, line in enumerate((BACKEND_DIR / "prompts" / "evals" / "review.jsonl").read_text(encoding="utf-8").splitlines()):
        if line.strip():
            d = json.loads(line)
            items.append(("evals", i + 1, d["input"], d["context"], {"id": d["id"], **d.get("expect", {})}))
    sem = asyncio.Semaphore(6)

    async def label(item):
        src, k, inp, ctx, expect = item
        async with sem:
            out = await s.encoder.encode(inp, ctx)
        res = out.result
        lang = "zh" if src == "sonnet_zh" else "en"
        return {
            "schema_version": SCHEMA_VERSION, "run": "seeds", "session": f"seeds-{src}", "game_seed": 0, "turn": k, "attempt": 0,
            "persona": None, "lang": lang, "mode": inp["mode"], "violate_requested": None, "source": src,
            "input": inp, "context": ctx, "passages_tail": [], "precheck": None, "silent": False,
            "teacher": {"data": res.data, "meta": res.meta, "fallback": res.fallback, "retries": 0},
            "validity": res.data.get("validity"), "rule": s.encoder.rule.encode(inp, ctx), "outcome": "seed",
            "expect": expect, "ts": time.time(), "review_chars_in": 0, "review_chars_out": 0,
        }

    rows = await asyncio.gather(*(label(it) for it in items))
    out_dir = DATA_ROOT / "raw" / "seeds"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "turns.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    fb = sum(r["teacher"]["fallback"] for r in rows)
    print(f"{len(rows)} seed records -> {out_dir / 'turns.jsonl'} (teacher fallbacks: {fb})")


def main() -> None:
    load_env()
    os.environ["LLM_LIVE_ROLES"] = "review"
    os.environ["MODEL_SHADOW"] = "0"
    os.environ["MODEL_ENCODER"] = "llm"
    os.environ["LLM_CACHE"] = "0"
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
