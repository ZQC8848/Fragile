"""Scripted players for whole-session tests: each looks at the session and returns this turn's channels.

They stand in for the self-play personas of M6 (backend-design.md §5.1), without an LLM.
"""

from __future__ import annotations

import random
from typing import Any

Channels = dict[str, Any]


def _asks(s) -> dict[str, Any] | None:
    return (s.run.asking_step() or {}).get("asks") if s.run else None


def curious(s) -> Channels:
    """The golden-path guest: goes along, sides with Mia, follows the clues, tells Nora the truth."""
    st, asks = s.state, _asks(s)
    if st["nora_call"] == "ringing":
        return {"action": "I answer the phone."}
    if s.run and s.run.invite_pending:
        return {"speech": "Sure."}
    if asks and asks["asker"] == "nora":
        return {"speech": "He was here. Leo was here this afternoon.", "addressee": "nora"}
    if asks and asks["kind"] == "side":
        return {"speech": "You're right, Mia.", "addressee": "mia"}
    if asks:
        return {"speech": "I don't know."}
    if st["player_room"] == "balcony" and "car_downstairs" not in st["revealed"]:
        return {"speech": "Isn't that Leo's car?", "addressee": "julian"}
    if st["story_phase"] != "early" and st["player_phone"] == "unchecked":
        return {"action": "I listen to the voicemail on my phone."}
    if {"missed_call", "car_downstairs"} <= set(st["revealed"]) and "leo_dead" not in st["revealed"]:
        return {"speech": "Leo left me a voicemail. And his car is still downstairs.", "addressee": "both"}
    return {"expression": "I wait."}


def ignores_the_call(s) -> Channels:
    if s.state["nora_call"] == "ringing":
        return {"expression": "I let it ring."}
    return curious(s)


def leaver(s) -> Channels:
    """Wants out as soon as dinner is served."""
    if s.state["player_room"] == "hall":
        return {"action": "I walk out the front door."}
    if s.state["player_room"] == "living":
        return {"action": "I go to the hall."}
    return {"action": "I go back inside."}


def police_caller(s) -> Channels:
    """Slips out to the balcony early, where nobody follows yet, and calls the police."""
    st = s.state
    if st["player_room"] == "balcony" and st["julian_room"] != "balcony":
        return {"action": "I call the police."}
    if st["player_room"] == "living" and st["turn_count"] >= 2:
        return {"action": "I go to the balcony."}
    return {"expression": "I smile."}


PHRASES = [
    {"speech": "Where's Leo tonight?"},
    {"speech": "What's in the crate?", "addressee": "julian"},
    {"speech": "Are you okay?", "addressee": "mia"},
    {"speech": "You're right."},
    {"speech": "That's not what happened."},
    {"speech": "Remember college? The four of us?"},
    {"speech": "Why are you moving, really?"},
    {"speech": "What happened this afternoon?"},
    {"speech": "I won't tell anyone."},
    {"speech": "I'm going to tell Nora."},
    {"speech": "Julian, you're lying."},
    {"action": "I knock on the crate."},
    {"action": "I look out of the window."},
    {"action": "I go to the kitchen."},
    {"action": "I go to the balcony."},
    {"action": "I go back inside."},
    {"action": "I go to the hall."},
    {"action": "I take the screwdriver."},
    {"action": "I open the crate."},
    {"action": "I search Julian's jacket."},
    {"action": "I listen to the voicemail."},
    {"action": "I answer the phone."},
    {"action": "I call Leo."},
    {"action": "I hug Mia."},
    {"action": "I examine the photo."},
    {"expression": "I stare at Julian."},
    {},
]


def randomized(seed: int):
    rng = random.Random(seed)

    def play(s) -> Channels:
        asks = _asks(s)
        if asks and asks["asker"] == "nora" and rng.random() < 0.7:
            return rng.choice([
                {"speech": "He was here.", "addressee": "nora"},
                {"speech": "No, I haven't seen him.", "addressee": "nora"},
                {"speech": "I don't know.", "addressee": "nora"},
            ])
        return dict(rng.choice(PHRASES))

    return play


async def play_to_end(session, player, max_turns: int = 80) -> list[dict[str, Any]]:
    records = []
    for _ in range(max_turns):
        if session.phase != "playing":
            break
        rec = await session.submit(player(session), "filled")
        if rec is not None:
            records.append(rec)
    return records
