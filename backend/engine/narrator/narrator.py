"""The narrator (interaction-design.md §9): one first-person passage per turn, as segments.

The turn loop hands it everything already decided: the player's input, what the world did with it, the
reactions to perform, the steps to deliver, the clock events and the next beat's opening. The narrator only
writes. It reports `steps_delivered` so the engine can check it against the plan (plan.md §3.1).

The offline mock stitches the authored texts together in order, which makes a mock playthrough read like a
stage script: useful for testing the engine, not as prose.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from engine.llm import LLMOutputError, extract_json, get_client
from engine.models.prompts import system_prompt
from engine.paths import SCHEMAS_DIR

NARRATOR_SCHEMA = json.loads((SCHEMAS_DIR / "llm" / "narrator.json").read_text(encoding="utf-8"))

PRONOUNS = {"female": "she/her", "male": "he/him", "nonbinary": "they/them"}

#: used when a segment fails the guard twice (interaction-design.md §9.4)
DEFLECTIONS = {
    "julian": "Julian tops up your glass. 'Anyway. Australia. Did I tell you about the flat?'",
    "mia": "Mia gets up to fetch more napkins. 'Is anyone cold? I can close the window.'",
    "nora": "Nora checks her phone again. 'I just want to know where he is.'",
}
NEUTRAL_NARRATION = "For a moment nobody says anything. Somewhere below, a car door slams."


@dataclass
class NarrationRequest:
    name: str
    gender: str
    turn: int
    room: str
    present: list[str]
    player: dict[str, Any] | None = None
    world: dict[str, Any] | None = None
    reactions: list[dict[str, Any]] = field(default_factory=list)
    outcome: dict[str, Any] | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    resume: bool = False
    events: list[str] = field(default_factory=list)
    fast_forward: bool = False
    opening: dict[str, Any] | None = None
    ending: dict[str, Any] | None = None
    prologue: str | None = None
    knowledge: dict[str, Any] = field(default_factory=dict)
    words: tuple[int, int] = (80, 140)
    recent: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        d = asdict(self)
        d["pronouns"] = PRONOUNS.get(self.gender, "they/them")
        d["steps"] = [{"id": s["id"], "do": s["do"], "length": s.get("length", "normal")} for s in self.steps]
        return d


@dataclass
class NarrationOutput:
    segments: list[dict[str, Any]]
    steps_delivered: list[str]
    hook: str
    meta: dict[str, Any] = field(default_factory=dict)
    fallback: bool = False

    def public(self) -> dict[str, Any]:
        return {"segments": self.segments, "steps_delivered": self.steps_delivered, "hook": self.hook, "meta": self.meta, "fallback": self.fallback}


def fill(text: str, name: str) -> str:
    return text.replace("{name}", name)


def line_segments(text: str, speaker: str | None, name: str) -> list[dict[str, Any]]:
    """An authored line as segments: a pure quoted line by a known speaker is speech, anything else narration."""
    text = fill(text.strip(), name)
    if speaker and re.fullmatch(r"'[^']*(?:'[a-z][^']*)*'", text):
        return [{"kind": "speech", "speaker": speaker, "text": text[1:-1]}]
    m = re.fullmatch(r"(Julian|Mia|Nora):\s*'(.+)'", text)
    if m and "' " not in m.group(2) and ": '" not in m.group(2):
        return [{"kind": "speech", "speaker": m.group(1).lower(), "text": m.group(2)}]
    return [{"kind": "narration", "text": text}]


def mock_passage(req: dict[str, Any]) -> dict[str, Any]:
    """Deterministic offline narrator: the decided pieces in order, authored text as written."""
    name = req["name"]
    segs: list[dict[str, Any]] = []
    if req.get("prologue"):
        segs += [{"kind": "narration", "text": p} for p in req["prologue"].split("\n") if p.strip()]
    player = req.get("player") or {}
    did = " ".join(filter(None, [player.get("action"), player.get("expression")])).strip()
    if did:
        segs.append({"kind": "me", "text": did if re.match(r"^(i|my)\b", did, re.I) else f"I {did[0].lower()}{did[1:]}"})
    if player.get("speech"):
        segs.append({"kind": "me_speech", "text": player["speech"]})
    world = req.get("world") or {}
    if world.get("note"):
        segs += line_segments(world["note"], None, name)
    for note in world.get("follow_notes") or []:
        segs += line_segments(note, None, name)
    for r in req.get("reactions") or []:
        segs += line_segments(r["do"], r.get("responder"), name)
    if req.get("outcome"):
        segs += line_segments(req["outcome"]["text"], None, name)
    if req.get("resume") and req.get("steps"):
        segs.append({"kind": "narration", "text": "The talk finds its way back to where it was."})
    for s in req.get("steps") or []:
        segs += line_segments(s["do"], None, name)
    for e in req.get("events") or []:
        segs += line_segments(e, None, name)
    if req.get("fast_forward"):
        segs.append({"kind": "narration", "text": "For a long while nobody says much."})
    if req.get("opening"):
        segs += line_segments(req["opening"]["text"], None, name)
    ending = req.get("ending") or {}
    for s in ending.get("steps") or []:
        segs += line_segments(s["do"], None, name)
    if ending.get("epilogue"):
        segs.append({"kind": "narration", "text": fill(ending["epilogue"], name)})
    if not segs:
        segs.append({"kind": "narration", "text": NEUTRAL_NARRATION})
    return {"segments": segs, "steps_delivered": [s["id"] for s in req.get("steps") or []], "hook": segs[-1]["text"][:120]}


class Narrator:
    def __init__(self, temperature: float = 0.8):
        self.client = get_client("narrator", temperature, mock_handler=self._mock)

    @staticmethod
    def _mock(system: str, user: str) -> dict[str, Any]:
        return mock_passage(extract_json(user))

    async def write(self, req: NarrationRequest) -> NarrationOutput:
        prompt = system_prompt("narrator")
        payload = req.payload()
        hints = "\n".join(f"- {h}" for h in req.hints)
        user = (
            "Write this turn's passage. Return only the JSON object."
            + (f"\nYOUR LAST DRAFT WAS REJECTED. Fix these problems:\n{hints}" if hints else "")
            + f"\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n```"
        )
        try:
            res = await self.client.call_json(prompt.text, user, schema=NARRATOR_SCHEMA, prompt_version=prompt.version)
        except LLMOutputError as e:
            # unusable output: the decided pieces, as the mock would stage them (plan.md §3.2 fallback)
            data = mock_passage(payload)
            return NarrationOutput(data["segments"], data["steps_delivered"], data["hook"], e.result.meta(), fallback=True)
        d = res.data
        segs = [{**s, "text": fill(s["text"], req.name)} for s in d["segments"]]
        return NarrationOutput(segs, list(d["steps_delivered"]), d.get("hook", ""), res.meta())


def repair(segments: list[dict[str, Any]], failures: list[dict[str, Any]], player: dict[str, Any] | None) -> list[dict[str, Any]]:
    """After two failed rewrites, replace each failing segment: an NPC line with that speaker's deflection, a
    narration with a neutral line, the player's own segments with their input as written."""
    bad = {f["index"] for f in failures}
    out: list[dict[str, Any]] = []
    neutral_used = False
    for i, seg in enumerate(segments):
        if i not in bad:
            out.append(seg)
            continue
        kind = seg.get("kind")
        if kind == "speech":
            out.append({"kind": "narration", "text": DEFLECTIONS.get(seg.get("speaker") or "", NEUTRAL_NARRATION)})
        elif kind == "narration" and not neutral_used:
            out.append({"kind": "narration", "text": NEUTRAL_NARRATION})
            neutral_used = True
        elif kind == "me_speech" and player and player.get("speech"):
            out.append({"kind": "me_speech", "text": player["speech"]})
        elif kind == "me" and player and (player.get("action") or player.get("expression")):
            out.append({"kind": "me", "text": " ".join(filter(None, [player.get("action"), player.get("expression")]))})
    return out or [{"kind": "narration", "text": NEUTRAL_NARRATION}]
