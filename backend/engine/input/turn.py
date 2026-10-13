"""The transient `turn` namespace rules read (schemas/state_v2.json $defs.Turn), built from M2's output.

One action unit per turn (interaction-design.md §4.4): the first one the encoder found. The streak fields look
at this turn and the two before it, for the pattern reactions.
"""

from __future__ import annotations

import re
from typing import Any

STREAK = 3

#: speech that says out loud the police are being called (plan.md R17)
POLICE_WORDS = re.compile(r"\b(police|cops?|911|emergency services)\b", re.I)
#: an action that takes a host along (plan.md R22): a cue word and the host's name in the same action text
LEAD_CUES = re.compile(r"\b(with me|with her|with him|take|takes|taking|bring|brings|bringing|lead|leads|leading|pull|pulls|pulling|"
                       r"drag|drags|dragging|guide|guides|guiding|steer|steers|steering|hand|hands|arm|arms)\b", re.I)
HOSTS = re.compile(r"\b(mia|julian)\b", re.I)


def leads(action_text: str) -> str | None:
    """The host an action takes along, if any: "I keep hold of Mia's hand and go to the hall" -> mia."""
    m = HOSTS.search(action_text or "")
    return m.group(1).lower() if m and LEAD_CUES.search(action_text) else None


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
    speech = (output.get("channels") or {}).get("speech") or ""
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
        "declared_police": not silent and ("threaten_to_tell" in acts or bool(POLICE_WORDS.search(speech))),
        "side_answer": None if silent else output.get("side_answer"),
        "leads": None if silent else leads((output.get("channels") or {}).get("action") or ""),
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
