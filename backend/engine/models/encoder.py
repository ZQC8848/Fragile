"""M2, the player-input encoder, behind one interface with three paths (backend-design.md §4.2, §7.2).

    encode(turn_input, context) -> EncoderOutput

`turn_input` is {"mode": "single", "text": ...} or {"mode": "channels", "channels": {...}}; `context` carries
the room, who is present, the last NPC lines and whether a call with Nora is open. The output is the shape of
schemas/llm/review.json: channels, translation flag, validity and rewrite, units, suspicion, claims, coverage
(the OOD seed) and Nora's answer.

The `llm` path is the `review` role: one call that splits, translates, validates, rewrites and classifies.
Offline its mock answers with the rule encoder. If the output is still unusable after one retry, the turn is
treated as valid with no units (plan.md §3.2) and the fallback is logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from engine.llm import LLMOutputError, extract_json, get_client
from engine.models.base import SlotRun, path_from_env, run_slot, shadow_from_env
from engine.models.prompts import system_prompt
from engine.models.rule_encoder import RuleEncoder
from engine.paths import SCHEMAS_DIR

REVIEW_SCHEMA = json.loads((SCHEMAS_DIR / "llm" / "review.json").read_text(encoding="utf-8"))


@dataclass
class EncoderOutput:
    data: dict[str, Any]
    path: str
    meta: dict[str, Any] = field(default_factory=dict)
    fallback: bool = False

    # -- views the turn loop uses ---------------------------------------------------------------
    @property
    def channels(self) -> dict[str, Any]:
        return self.data.get("channels") or {}

    @property
    def validity(self) -> dict[str, Any]:
        return self.data.get("validity") or {"label": "ok"}

    @property
    def ok(self) -> bool:
        return self.validity.get("label") == "ok"

    @property
    def units(self) -> list[dict[str, Any]]:
        return self.data.get("units") or []

    def public(self) -> dict[str, Any]:
        return {"path": self.path, "fallback": self.fallback, "meta": self.meta, **self.data}


def empty_output(channels: dict[str, Any]) -> dict[str, Any]:
    """The fallback: valid, nothing understood."""
    return {
        "channels": channels,
        "translated": False,
        "validity": {"label": "ok", "span": None, "message": None},
        "rewrite": None,
        "units": [],
        "suspicion": 0.0,
        "claims": [],
        "coverage": 0.0,
        "nora_answer": None,
    }


class RuleEncoderPath:
    path = "rule"

    def __init__(self, rule: RuleEncoder):
        self.rule = rule

    async def encode(self, turn_input: dict[str, Any], context: dict[str, Any]) -> EncoderOutput:
        return EncoderOutput(self.rule.encode(turn_input, context), self.path)


class LLMEncoderPath:
    path = "llm"

    def __init__(self, rule: RuleEncoder, temperature: float = 0.0, action_table: str = ""):
        self.rule = rule
        self.action_table = action_table
        self.client = get_client("review", temperature, mock_handler=self._mock)

    def _mock(self, system: str, user: str) -> dict[str, Any]:
        req = extract_json(user)
        return self.rule.encode(req["input"], req["context"])

    async def encode(self, turn_input: dict[str, Any], context: dict[str, Any]) -> EncoderOutput:
        prompt = system_prompt("review", ACTION_TABLE=self.action_table)
        payload = {"input": turn_input, "context": context}
        user = (
            "Review this turn of player input. Return only the JSON object.\n\n"
            f"```json\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n```"
        )
        try:
            res = await self.client.call_json(prompt.text, user, schema=REVIEW_SCHEMA, prompt_version=prompt.version)
        except LLMOutputError as e:
            channels = self.rule.segment(turn_input)
            return EncoderOutput(empty_output(channels), self.path, e.result.meta(), fallback=True)
        return EncoderOutput(res.data, self.path, res.meta())


class TrainedEncoderPath:
    """Placeholder for the DeBERTa student: delegates to the llm path, visibly."""

    path = "trained"
    delegates = True

    def __init__(self, llm: LLMEncoderPath):
        self.llm = llm

    async def encode(self, turn_input: dict[str, Any], context: dict[str, Any]) -> EncoderOutput:
        out = await self.llm.encode(turn_input, context)
        return EncoderOutput(out.data, self.path, {**out.meta, "delegated_to": "llm"}, out.fallback)


class Encoder:
    def __init__(
        self, objects: dict[str, dict[str, Any]], active: str | None = None, shadow: bool | None = None, action_table: str = ""
    ):
        self.rule = RuleEncoder(objects)
        llm = LLMEncoderPath(self.rule, action_table=action_table)
        self.paths = {"rule": RuleEncoderPath(self.rule), "llm": llm, "trained": TrainedEncoderPath(llm)}
        self.active = active or path_from_env("encoder")
        self.shadow = shadow_from_env() if shadow is None else shadow

    async def encode(self, turn_input: dict[str, Any], context: dict[str, Any]) -> SlotRun:
        return await run_slot(
            self.paths, self.active, self.shadow,
            lambda p: p.encode(turn_input, context),
            lambda r, name: EncoderOutput(r.data, name, {**r.meta, "delegated_to": "llm"}, r.fallback),
        )
