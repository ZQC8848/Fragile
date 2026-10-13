"""System prompts for the LLM roles: backend/prompts/<role>_v<N>.md when present (plan.md §3.2), otherwise
the short built-in v0 below.

The v0 texts only state the task and the output contract, enough for the turn loop to run against a real
provider. Prompt v1 with full instructions and eval sets is milestone M4; each lands as <role>_v1.md and
takes over automatically.
"""

from __future__ import annotations

from engine.llm import Prompt, load_prompt

BUILTIN_V0: dict[str, str] = {
    "review": (
        "You review one turn of player input for a turn-based interactive drama. The player may only write their "
        "own words, actions and expressions. Split single-box input into speech, action and expression and guess "
        "the addressee; translate non-English text to English (set translated); judge validity (ok, npc_action, "
        "npc_speech, outcome, perception, invention, stride, absurd, out_of_scope, meta) and give the offending "
        "span, a one-sentence system-voice message and a rewrite that keeps the intent (null for absurd, "
        "out_of_scope, meta); classify every unit (discourse act, addressee, topics, action as verb/target from "
        "the closed action table, implausible); rate suspicion 0-3; list facts the player claims in speech; rate "
        "coverage 0-1; and when the input is addressed to Nora say whether it tells her the truth about Leo, a "
        "lie, or neither. Reply with JSON only, matching the schema you were given."
    ),
    "narrator": (
        "You are the narrator of a turn-based interactive drama told in the first person by the player character. "
        "Write one passage as segments: me (the player's own action and expression, as written, never more), "
        "me_speech (the player's words), narration (what I see and hear), speech (an NPC line, with speaker). "
        "Perform the reaction you are given and deliver exactly the steps you are given, in order, then the "
        "events and the next opening if any. Never add the player's words, actions, decisions, feelings or "
        "thoughts. Characters only say what their knowledge slice allows. Never describe the body. No dashes in "
        "dialogue. End on something the player can answer. Reply with JSON: "
        '{"segments": [...], "steps_delivered": [step ids], "hook": "..."}.'
    ),
    "guard": (
        "You check each segment of a narrated passage. Labels: consistent; premature_leak (states a fact that is "
        "not unlocked); contradiction (contradicts the facts, or a character reacts to something they did not "
        "hear); player_overreach (writes words, actions, decisions or inner states for the player beyond their "
        "input). Reply with JSON: {\"verdicts\": [{\"index\", \"label\", \"fact\", \"span\", \"confidence\"}]}."
    ),
    "tension": (
        "Rate the dramatic tension of the last few turns of an interactive drama from 0 (calm) to 5 (climax). "
        'Reply with JSON: {"tension": <number>, "reason": "<one sentence>"}.'
    ),
    "options": (
        "Offer the player three next moves in channel form, one per strategy: respond (answer what the scene asks), "
        "probe (follow a clue or topic the player already knows), social (side with, comfort or push back on "
        "someone). Neutral voice; never give the player a personality; only use what the player already knows. "
        'Reply with JSON: {"options": [{"speech", "action", "expression", "addressee", "strategy"}]}.'
    ),
}


def system_prompt(role: str, **variables: str) -> Prompt:
    """The role's prompt with `{{NAME}}` placeholders filled from `variables` (e.g. the review prompt's action
    table, generated from data/interactions.yaml so it never drifts from the world rules)."""
    try:
        prompt = load_prompt(role)
    except FileNotFoundError:
        if role not in BUILTIN_V0:
            raise
        prompt = Prompt(BUILTIN_V0[role], 0)
    text = prompt.text
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", value)
    return Prompt(text, prompt.version)
