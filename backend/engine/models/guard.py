"""M3, the consistency guard, behind one interface with three paths (backend-design.md §4.3, §7.2).

    check(segments, ctx) -> list of verdicts, one per segment
    verdict = {index, label, fact, span, confidence}; label in consistent | premature_leak |
              contradiction | player_overreach

`ctx` is a GuardContext: which facts the narration may state, which each speaker may state, and the player's
own input. The rule path matches fact phrases and compares the player's segments with the input; it never
judges contradictions (that needs reading, so it is left to the llm and trained paths). It is deliberately
conservative: a guard that blocks too much kills the scene (backend-design.md §11).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from engine.llm import LLMOutputError, extract_json, get_client
from engine.models.base import SlotRun, path_from_env, run_slot, shadow_from_env
from engine.models.prompts import system_prompt
from engine.paths import SCHEMAS_DIR

GUARD_SCHEMA = json.loads((SCHEMAS_DIR / "llm" / "guard.json").read_text(encoding="utf-8"))

#: phrases that state a fact outright; hints and jokes ("the bodies of my enemies") do not match
FACT_PATTERNS: dict[str, re.Pattern[str]] = {
    "car_downstairs": re.compile(r"\bleo'?s (car|hatchback)\b", re.I),
    "missed_call": re.compile(r"\bleo'?s voicemail\b|\bleo (called|rang) (you|me) twice\b", re.I),
    "leo_was_here": re.compile(r"\b(leo|he) (was|came) (here|by|over) (this afternoon|earlier|today)\b|\bleo was here\b", re.I),
    "embezzlement": re.compile(r"\b(studio money|studio account|embezzl\w*|took the money)\b", re.I),
    "mia_called_leo": re.compile(r"\b(mia|i|she) called (him|leo) (over|here)\b|\bmia called leo\b", re.I),
    "leo_wanted_money": re.compile(r"\b(came|come) for (his share|the money|money)\b|\bwanted his share\b", re.I),
    "leo_dead": re.compile(r"\b(leo|he)('?s| is) dead\b|\bkilled (him|leo)\b|\b(stopped|wasn'?t|isn'?t) breathing\b", re.I),
    "body_in_crate": re.compile(r"\b(body|corpse)\b|\b(he|leo)('?s| is) in the crate\b", re.I),
    "who_struck": re.compile(r"\b(hit|struck) him with the bottle\b|\bit was mia\b", re.I),
    "nora_pushed_leo": re.compile(r"\bnora (sent|pushed|urged) him\b", re.I),
}

_WORD = re.compile(r"[a-z0-9']+")


@dataclass
class GuardContext:
    #: facts any segment may state: revealed, plus what this turn's beat, reaction or world note discloses
    allowed: set[str] = field(default_factory=set)
    #: per speaker, facts they may say on top of `allowed` (knowledge cards, may_say_when)
    speaker_allowed: dict[str, set[str]] = field(default_factory=dict)
    player: dict[str, Any] = field(default_factory=dict)
    #: the scene is an ending: everything may come out
    ending: bool = False
    #: knowledge slice and recent context for the llm path
    knowledge: dict[str, Any] = field(default_factory=dict)

    def public(self) -> dict[str, Any]:
        return {
            "allowed": sorted(self.allowed),
            "speaker_allowed": {k: sorted(v) for k, v in self.speaker_allowed.items()},
            "player": self.player,
            "ending": self.ending,
        }


def _overlap(a: str, b: str) -> float:
    wa, wb = set(_WORD.findall(a.lower())), set(_WORD.findall(b.lower()))
    return len(wa & wb) / max(1, len(wa))


def rule_verdicts(segments: list[dict[str, Any]], ctx: GuardContext) -> list[dict[str, Any]]:
    out = []
    speech = (ctx.player.get("speech") or "").strip()
    did = " ".join(filter(None, [ctx.player.get("action"), ctx.player.get("expression")])).strip()
    for i, seg in enumerate(segments):
        verdict = {"index": i, "label": "consistent", "fact": None, "span": None, "confidence": 0.6}
        kind, text = seg.get("kind"), seg.get("text") or ""
        if kind == "me_speech":
            if not speech or _overlap(text, speech) < 0.6:
                verdict.update(label="player_overreach", span=text, confidence=0.7)
        elif kind == "me":
            if not did and not ctx.player.get("world_note"):
                verdict.update(label="player_overreach", span=text, confidence=0.5)
        elif not ctx.ending:
            allowed = ctx.allowed | (ctx.speaker_allowed.get(seg.get("speaker") or "", set()) if kind == "speech" else set())
            for fact, rx in FACT_PATTERNS.items():
                m = rx.search(text)
                if m and fact not in allowed:
                    verdict.update(label="premature_leak", fact=fact, span=m.group(0), confidence=0.8)
                    break
        out.append(verdict)
    return out


class RuleGuardPath:
    path = "rule"

    async def check(self, segments: list[dict[str, Any]], ctx: GuardContext) -> dict[str, Any]:
        return {"verdicts": rule_verdicts(segments, ctx), "meta": {}, "fallback": False}


class LLMGuardPath:
    path = "llm"

    def __init__(self, temperature: float = 0.0):
        self.client = get_client("guard", temperature, mock_handler=self._mock)

    @staticmethod
    def _mock(system: str, user: str) -> dict[str, Any]:
        req = extract_json(user)
        ctx = GuardContext(
            allowed=set(req["allowed_facts"]),
            speaker_allowed={k: set(v) for k, v in req["speaker_allowed"].items()},
            player=req["player_input"],
            ending=req["ending"],
        )
        return {"verdicts": rule_verdicts(req["segments"], ctx)}

    async def check(self, segments: list[dict[str, Any]], ctx: GuardContext) -> dict[str, Any]:
        prompt = system_prompt("guard")
        payload = {
            "segments": [{"index": i, **s} for i, s in enumerate(segments)],
            "allowed_facts": sorted(ctx.allowed),
            "speaker_allowed": {k: sorted(v) for k, v in ctx.speaker_allowed.items()},
            "player_input": ctx.player,
            "ending": ctx.ending,
            "knowledge": ctx.knowledge,
        }
        user = f"Check every segment. Return only the JSON object.\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n```"
        try:
            res = await self.client.call_json(prompt.text, user, schema=GUARD_SCHEMA, prompt_version=prompt.version)
        except LLMOutputError as e:
            # unusable guard output counts as a pass (plan.md §3.2)
            passes = [{"index": i, "label": "consistent", "fact": None, "span": None, "confidence": 0.0} for i in range(len(segments))]
            return {"verdicts": passes, "meta": e.result.meta(), "fallback": True}
        by_index = {v["index"]: v for v in res.data["verdicts"]}
        verdicts = [by_index.get(i, {"index": i, "label": "consistent", "fact": None, "span": None, "confidence": 0.0}) for i in range(len(segments))]
        return {"verdicts": verdicts, "meta": res.meta(), "fallback": False}


class TrainedGuardPath:
    path = "trained"
    delegates = True

    def __init__(self, llm: LLMGuardPath):
        self.llm = llm

    async def check(self, segments: list[dict[str, Any]], ctx: GuardContext) -> dict[str, Any]:
        out = await self.llm.check(segments, ctx)
        return {**out, "meta": {**out["meta"], "delegated_to": "llm"}}


class Guard:
    def __init__(self, active: str | None = None, shadow: bool | None = None):
        llm = LLMGuardPath()
        self.paths = {"rule": RuleGuardPath(), "llm": llm, "trained": TrainedGuardPath(llm)}
        self.active = active or path_from_env("guard")
        self.shadow = shadow_from_env() if shadow is None else shadow

    async def check(self, segments: list[dict[str, Any]], ctx: GuardContext) -> SlotRun:
        return await run_slot(
            self.paths, self.active, self.shadow,
            lambda p: p.check(segments, ctx),
            lambda r, name: {**r, "meta": {**r["meta"], "delegated_to": "llm"}},
        )

    @staticmethod
    def failures(verdicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [v for v in verdicts if v["label"] != "consistent"]
