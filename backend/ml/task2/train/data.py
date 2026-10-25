"""Load task 2 examples and derive the comparable, turn-level targets every system is scored on.

Every rung (rule, TF-IDF, embeddings, mDeBERTa) is evaluated on the same turn-level heads, so they can sit
in one table:

  act_set    multi-label: which dialogue acts occur in the turn
  topics     multi-label: union of the units' topics
  claims     multi-label
  addressee  single label (single-box inputs only; in channels mode the player chose it)
  action     single label "verb:target" or "none"
  suspicion  0-3 (regression; scored by MAE and quadratic-weighted kappa)
  nora       truth / lie / none, only when the turn was addressed to Nora
  side       julian / mia / none, only when the scene asked the player to take a side
  seg        segmentation, scored per character (whitespace skipped), single-box inputs only

Standard library only (the baselines add scikit-learn / transformers on top).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..common.labels import ACTS, CLAIMS, TOPICS

HEADS_MULTI = {"act_set": ACTS, "topics": TOPICS, "claims": CLAIMS}
HEADS_SINGLE = ("addressee", "action", "nora", "side")


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def targets_from_review(data: dict[str, Any]) -> dict[str, Any]:
    """Turn-level targets from any review-shaped output (teacher, rule, or a model's prediction)."""
    units = data.get("units") or []
    act = next((u["action"] for u in units if u.get("action")), None)
    return {
        "act_set": sorted({u.get("act") for u in units if u.get("act")}),
        "topics": sorted({t for u in units for t in (u.get("topics") or [])}),
        "claims": sorted(set(data.get("claims") or [])),
        "addressee": (data.get("channels") or {}).get("addressee") or "none",
        "action": f"{act['verb']}:{act['target']}" if act else "none",
        "suspicion": float(data.get("suspicion") or 0.0),
        "nora": data.get("nora_answer") or "none",
        "side": data.get("side_answer") or "none",
    }


def targets(ex: dict[str, Any]) -> dict[str, Any]:
    """Turn-level targets of an example (built from the teacher labels)."""
    units = ex["units"]
    act = next((u["action"] for u in units if u.get("action")), None)
    t = ex["turn_labels"]
    return {
        "act_set": sorted({u["act"] for u in units if u.get("act")}),
        "topics": sorted({x for u in units for x in u.get("topics") or []}),
        "claims": sorted(set(t.get("claims") or [])),
        "addressee": t.get("addressee") or "none",
        "action": f"{act['verb']}:{act['target']}" if act else "none",
        "suspicion": float(t.get("suspicion") or 0.0),
        "nora": t.get("nora_answer") or "none",
        "side": t.get("side_answer") or "none",
    }


def head_mask(ex: dict[str, Any], head: str) -> bool:
    m = ex["mask"]
    return {"addressee": m["addressee"], "nora": m["nora"], "side": m["side"], "seg": m["seg"]}.get(head, True)


def char_tags(text: str, segments: list[dict[str, Any]]) -> list[str]:
    """Per-character tag (O/S/A/E) from character spans."""
    tags = ["O"] * len(text)
    code = {"speech": "S", "action": "A", "expression": "E"}
    for sp in segments:
        for i in range(sp["start"], min(sp["end"], len(text))):
            tags[i] = code[sp["channel"]]
    return tags


def model_input(ex: dict[str, Any], with_context: bool = True) -> str:
    return f"{ex['text']} || {ex['context_text']}" if with_context else ex["text"]
