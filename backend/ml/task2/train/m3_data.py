"""M3 (narration guard) examples: one per segment, the model inputs, and the rule that composes guard verdicts.

Example (built by gen/m3_build.py, one JSON line per segment):
  ex_id, turn_id, session, split, source (selfplay | synth | logged), index, kind, speaker, text,
  player_input, scene, previous_passage (tail), opening, ending, revealed,
  labels {facts, overreach, overreach_span [s, e] | null, contradiction, contradiction_span [s, e] | null, note}

The model reads the segment as the first sequence and its context as the second:
  "[me] I pick up the glass."   </s>   "player: ... || scene: ... || flags: ... || before: ... || heard: ..."
Standard library only (runs on Windows / CARC without the engine).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FACTS = ["car_downstairs", "missed_call", "leo_was_here", "embezzlement", "mia_called_leo", "leo_wanted_money",
         "leo_dead", "body_in_crate", "who_struck", "nora_pushed_leo"]
BINARY = ("overreach", "contradiction")
LABELS = ("consistent", "premature_leak", "contradiction", "player_overreach")
PREV_CHARS = 700


def load_splits(data_dir: str | Path) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for p in sorted(Path(data_dir).glob("*.jsonl")):
        out[p.stem] = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return out


def seg_text(ex: dict[str, Any]) -> str:
    who = f"{ex['kind']}:{ex['speaker']}" if ex.get("speaker") else ex["kind"]
    return f"[{who}] {ex['text']}"


def scene_text(sc: dict[str, Any]) -> str:
    parts = [f"I am in the {sc.get('room')}", "present: " + (", ".join(sc.get("present") or []) or "nobody"),
             "rooms: " + ", ".join(f"{n} {sc.get(f'{n}_room')}" for n in ("julian", "mia", "nora")),
             f"crate {sc.get('crate')}, leo_phone {sc.get('leo_phone')}, my phone {sc.get('player_phone')}, nora_call {sc.get('nora_call')}"]
    if sc.get("moves"):
        parts.append("moves: " + ", ".join(f"{m['who']} {m['from']}->{m['to']}" for m in sc["moves"]))
    return " | ".join(parts)


def heard_text(sc: dict[str, Any]) -> str:
    return "; ".join(f"{k} by {'/'.join(v)}" for k, v in (sc.get("heard_by") or {}).items())


def player_text(pi: dict[str, Any] | None) -> str:
    if not pi:
        return "player: (no input, opening)"
    bits = [f"{k} {pi[k]}" for k in ("speech", "action", "expression") if pi.get(k)]
    if pi.get("addressee"):
        bits.append(f"to {pi['addressee']}")
    return "player: " + (" | ".join(bits) if bits else "(silent)")


def context_text(ex: dict[str, Any]) -> str:
    flags = [f for f in ("opening", "ending") if ex.get(f)]
    prev = (ex.get("previous_passage") or "")[-PREV_CHARS:]
    # the long who-heard-what list goes last: truncation (only_second) drops it before the previous passage
    return " || ".join(filter(None, [player_text(ex.get("player_input")), "scene: " + scene_text(ex["scene"]),
                                     ("flags: " + ", ".join(flags)) if flags else "", "before: " + prev,
                                     "heard: " + heard_text(ex["scene"])]))


def find_span(text: str, span: str | None) -> tuple[int, int] | None:
    """Character offsets of a teacher span in the text (quotes the text does not have are stripped)."""
    if not span:
        return None
    for s in (span, span.strip(), span.strip().strip("\"“”'‘’「」")):
        i = text.find(s) if s else -1
        if i >= 0:
            return (i, i + len(s))
    return None


def compose(ex: dict[str, Any], facts: list[str], overreach: bool, contradiction: bool,
            allowed: set[str] | None = None) -> str:
    """The guard verdict for one segment from the three perceptions, by the game's own rules.

    premature_leak  a stated fact that is not allowed (allowed = facts revealed by the end of the turn, the logged
                    stand-in for GuardContext.allowed), outside the ending
    contradiction   as perceived
    player_overreach  as perceived, except in the opening passage, and in an ending outside my quoted speech
                    (Guard.failures). Priority when several apply: leak, contradiction, overreach."""
    allowed = set(ex.get("revealed") or []) if allowed is None else allowed
    if not ex.get("ending") and any(f not in allowed for f in facts):
        return "premature_leak"
    if contradiction:
        return "contradiction"
    if overreach and not (ex.get("opening") or (ex.get("ending") and ex["kind"] != "me_speech")):
        return "player_overreach"
    return "consistent"


def gold_label(ex: dict[str, Any]) -> str:
    lab = ex["labels"]
    return compose(ex, lab["facts"], lab["overreach"], lab["contradiction"])
