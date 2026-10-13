"""The story so far, for the narrator (plan.md R21).

The narrator sees only the last two passages. This ledger fills in the rest deterministically from the state
and the passages already shown, so it can never invent history: where everyone is and who moved this turn,
what has already happened that people would remember, and the NPC lines already spoken (not to be repeated
word for word).
"""

from __future__ import annotations

from typing import Any

PEOPLE = ("player", "julian", "mia", "nora")
ROOM_NAMES = {
    "hall": "the hall", "living": "the living room", "kitchen": "the kitchen", "balcony": "the balcony",
    "bathroom": "the bathroom", "outside": "outside the flat",
}
#: what a claim says, in the player's words (fact ids: guard_v1.md)
CLAIM_TEXT = {
    "car_downstairs": "the yellow car downstairs is Leo's", "missed_call": "Leo called me",
    "leo_was_here": "Leo was here", "embezzlement": "the studio money", "mia_called_leo": "Mia called Leo over",
    "leo_wanted_money": "Leo wanted his money", "leo_dead": "Leo is dead", "body_in_crate": "Leo is in the crate",
    "who_struck": "who hit him", "nora_pushed_leo": "Nora pushed Leo to go",
}
#: how many earlier NPC lines the narrator is shown
SAID_LINES = 24


def _who(person: str) -> str:
    return "I" if person == "player" else person.capitalize()


def _names(people: list[str]) -> str:
    names = [p.capitalize() for p in people]
    if not names:
        return "nobody"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def positions(state: dict[str, Any]) -> dict[str, str]:
    """Where everyone is now; Nora's "outside" means she has not arrived."""
    out = {_who(p): ROOM_NAMES.get(state.get(f"{p}_room"), str(state.get(f"{p}_room"))) for p in PEOPLE}
    if state.get("nora_room") == "outside":
        out["Nora"] = "not here (outside the building)"
    return out


def moves(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """Everyone whose room changed this turn, whatever moved them (an action, a host following, a scene's end)."""
    out = []
    for p in PEOPLE:
        a, b = before.get(f"{p}_room"), after.get(f"{p}_room")
        if a != b:
            out.append(f"{_who(p)}: {ROOM_NAMES.get(a, a)} -> {ROOM_NAMES.get(b, b)}")
    return out


def history(state: dict[str, Any]) -> list[str]:
    """What has already happened tonight, as plain sentences."""
    out: list[str] = []
    heard = state.get("heard_by") or {}
    if state.get("player_phone") == "voicemail_heard":
        who = [p for p in heard.get("missed_call", []) if p != "nora"]
        out.append("I have listened to Leo's voicemail" + (f" ({_names(who)} heard about it)." if who else "."))
    call = state.get("nora_call")
    if call == "answered":
        out.append("Nora phoned and I answered; " + _names(heard.get("noras_call", [])) + " heard the call.")
    elif call in ("missed", "declined"):
        out.append("Nora phoned and I did not answer.")
    if state.get("leo_phone") == "buzzed":
        out.append("A phone has buzzed inside Julian's jacket.")
    elif state.get("leo_phone") == "found":
        out.append("Leo's phone has been found in Julian's jacket.")
    told = state.get("nora_told")
    if told == "truth":
        out.append("I have told Nora something true about Leo tonight.")
    elif told == "lie":
        out.append("I have lied to Nora about Leo.")
    if state.get("threatened_julian"):
        out.append("Julian has heard me threaten to tell, or caught me reaching for the police.")
    if state.get("police_blocks"):
        out.append("Julian has already stopped me calling the police once.")
    if state.get("police_called"):
        out.append("I got through to the police.")
    if state.get("crate") == "opened":
        out.append("The crate is open.")
    told_to: dict[str, set[str]] = {}
    for c in state.get("claims") or []:
        told_to.setdefault(c["fact"], set()).add(c["to"])
    for fact, to in told_to.items():
        out.append(f"I have said out loud that {CLAIM_TEXT.get(fact, fact)} (to {', '.join(sorted(to))}).")
    done = [h["beat_id"].replace("_", " ") for h in state.get("beat_history") or [] if h.get("completed")]
    if done:
        out.append("Scenes already played: " + ", ".join(done) + ".")
    return out


def said(passages: list[dict[str, Any]], limit: int = SAID_LINES) -> list[str]:
    """NPC lines already spoken, oldest first, without duplicates."""
    lines: list[str] = []
    for p in passages:
        for s in p.get("segments") or []:
            if s.get("kind") == "speech" and s.get("speaker"):
                line = f"{s['speaker'].capitalize()}: {s['text']}"
                if line not in lines:
                    lines.append(line)
    return lines[-limit:]
