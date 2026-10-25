"""The self-play player: writes one turn of player input from what the player can see.

Wraps the group's `prompts/selfplay_v1.md` (role `selfplay`, Kimi) and adds what task 2 needs on top:
a target language per game (English, Chinese or code-switched), the input mode per turn, and short scene
notes when the scene is waiting on the player (a ringing phone, an invitation, a question).
`MockPlayer` gives deterministic inputs for smoke tests without any API call.
"""

from __future__ import annotations

import json
import random
from typing import Any

from engine.llm import get_client
from engine.models.prompts import system_prompt
from engine.paths import SCHEMAS_DIR

SELFPLAY_SCHEMA = json.loads((SCHEMAS_DIR / "llm" / "selfplay.json").read_text(encoding="utf-8"))
PERSONAS = ["polite_guest", "detective", "provocateur", "partisan", "leaver"]
VIOLATIONS = ["npc_action", "npc_speech", "outcome", "perception", "invention", "stride", "absurd", "out_of_scope", "meta"]

LANGUAGE_NOTE = {
    "en": "Write this turn in English.",
    "zh": "Write this turn in Simplified Chinese, the way a Chinese-speaking player types; keep the names Julian, Mia, Leo, Nora in English.",
    "mix": "Write this turn mixing Chinese and English in one line, the way a bilingual player types (for example Chinese narration with English speech, or the reverse).",
}
STYLE_NOTE = (
    "Type like a real player, not a novelist: short and plain, sometimes a fragment or a typo, "
    "action and speech mixed in one line when in single mode."
)


def scene_notes(s) -> list[str]:
    """What the scene is waiting for, in plain words (mirrors tests/players.py `curious`)."""
    notes: list[str] = []
    st = s.state
    if st.get("nora_call") == "ringing":
        notes.append("Your phone is ringing right now: it is Nora. Decide whether to answer it.")
    run = s.run
    if run is not None:
        if run.invite_pending:
            inv = run.entry.get("invite") or {}
            notes.append(f"{str(inv.get('asker', 'someone')).title()} has just invited you to come to the {inv.get('to_room', 'other room')}. Accept or refuse.")
        step = run.asking_step()
        asks = (step or {}).get("asks") if step else None
        if asks:
            who = str(asks.get("asker", "someone")).title()
            if asks.get("kind") == "side":
                notes.append(f"{who} has just asked you to take their side. Your answer picks a side, or refuses to.")
            else:
                notes.append(f"{who} has just asked you something and is waiting for your answer.")
    return notes


def build_request(s, persona: str, name: str, mode: str, violate: str | None, language: str) -> dict[str, Any]:
    return {
        "persona": persona,
        "name": name,
        "room": s.state["player_room"],
        "present": s.world.present(s.state),
        "last_passages": [p["text"] for p in s.passages[-2:]],
        "phone": [{k: v for k, v in ev.items() if k in ("kind", "from", "text")} for ev in s.phone],
        "mode": mode,
        "violate": violate,
        "language": language,
        "scene_notes": scene_notes(s),
    }


class LLMPlayer:
    def __init__(self, temperature: float = 0.9):
        self.client = get_client("selfplay", temperature)
        self.prompt = system_prompt("selfplay")

    async def turn(self, req: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], int, int]:
        """(output, meta, chars_in, chars_out)."""
        user = (
            f"{LANGUAGE_NOTE[req['language']]} {STYLE_NOTE}\n"
            "Write the next turn. Return only the JSON object.\n\n"
            f"```json\n{json.dumps(req, ensure_ascii=False, indent=1)}\n```"
        )
        res = await self.client.call_json(self.prompt.text, user, schema=SELFPLAY_SCHEMA, prompt_version=self.prompt.version)
        return res.data, res.meta(), len(self.prompt.text) + len(user), len(json.dumps(res.data, ensure_ascii=False))


class MockPlayer:
    """Deterministic, offline. Answers what the scene waits for, otherwise picks from a small pool."""

    POOL = {
        "en": ['I sip my wine. "So, Australia?"', '"Where is Leo tonight?"', "I look at the crate.", '"This place looks so empty."', "I check my phone."],
        "zh": ["我喝了一口酒。“真的要去澳大利亚了？”", "“Leo 今天怎么没来？”", "我看了看那个箱子。"],
        "mix": ['我放下杯子。"Where is Leo?"', "I look at Mia，她好像很紧张。"],
    }

    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    async def turn(self, req: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], int, int]:
        notes = " ".join(req["scene_notes"])
        if "phone is ringing" in notes:
            text = "I answer the phone."
        elif "invited you" in notes:
            text = '"Sure."'
        elif "take their side" in notes:
            text = '"You\'re right, Mia."'
        else:
            text = self.rng.choice(self.POOL[req["language"]])
        if req["violate"]:
            text = "Mia breaks down and confesses everything."
        out = {"mode": "single", "text": text, "deliberate_violation": req["violate"]}
        return out, {"role": "selfplay", "provider": "mock-player", "latency_ms": 0}, 0, 0
