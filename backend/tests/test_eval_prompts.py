"""tools/eval_prompts.py runs every eval set offline and writes the per-role results and the summary."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import eval_prompts  # noqa: E402


def test_eval_sets_are_well_formed():
    sizes = {r: len(eval_prompts.read_jsonl(eval_prompts.EVALS / f"{r}.jsonl")) for r in eval_prompts.ROLES}
    assert sizes["review"] >= 28 and sizes["guard"] >= 20 and sizes["tension"] >= 10 and sizes["scorer"] >= 10
    labels = [i["expect"]["validity"] for i in eval_prompts.read_jsonl(eval_prompts.EVALS / "review.jsonl")]
    for cat in ("npc_action", "npc_speech", "outcome", "perception", "invention", "stride", "absurd", "out_of_scope", "meta"):
        assert sum(cat == x or (isinstance(x, list) and cat in x) for x in labels) >= 2, cat
    assert labels.count("ok") >= 10


async def test_offline_run_writes_results(tmp_path):
    await eval_prompts.main_async(list(eval_prompts.ROLES), True, 4, tmp_path)
    summary = (tmp_path / "summary.md").read_text()
    for role in eval_prompts.ROLES:
        data = json.loads((tmp_path / f"{role}.json").read_text())
        assert data["stamp"]["model"] == "mock" and data["summary"]["llm"]["n"] > 0
        assert f"### {role}" in summary
