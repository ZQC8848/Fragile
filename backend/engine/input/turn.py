"""The transient `turn` namespace rules read (schemas/state_v2.json $defs.Turn), built from M2's output.

One action unit per turn (interaction-design.md §4.4): the first one the encoder found. The streak fields look
at this turn and the two before it, for the pattern reactions.
"""

from __future__ import annotations

from typing import Any

STREAK = 3


def build_turn(output: dict[str, Any], silent: bool, history: list[dict[str, Any]]) -> dict[str, Any]:
    """`output` is an encoder output (review.json shape); `history` holds earlier turns' namespaces, oldest first."""
    units = output.get("units") or []
    acts = [u["act"] for u in units if u.get("act")]
    topics: list[str] = []
    for u in units:
        for t in u.get("topics") or []:
            if t not in topics:
                topics.append(t)
    action = next((u["action"] for u in units if u.get("action")), None)
    addressee = (output.get("channels") or {}).get("addressee")
    if addressee is None:
        addressee = next((u.get("addressee") for u in units if u.get("addressee")), None)
    turn: dict[str, Any] = {
        "acts": ["silence"] if silent else acts,
        "addressee": None if silent else addressee,
        "topics": [] if silent else topics,
        "claims": [] if silent else list(output.get("claims") or []),
        "action": None if silent else (dict(action) if action else None),
        "blocked_by": None,
        "blocked_action": None,
        "silent": silent,
        "nora_answer": None if silent else output.get("nora_answer"),
        "streak_addressee": None,
        "streak_topic": None,
    }
    window = [*history[-(STREAK - 1):], turn]
    if len(window) == STREAK:
        addr = {t.get("addressee") for t in window}
        if len(addr) == 1 and (a := addr.pop()) in ("julian", "mia", "nora"):
            turn["streak_addressee"] = a
        common = set(window[0].get("topics") or [])
        for t in window[1:]:
            common &= set(t.get("topics") or [])
        if common:
            turn["streak_topic"] = sorted(common)[0]
    return turn
