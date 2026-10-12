"""M4, the tension estimator, behind one interface with three paths (backend-design.md §4.4, §7.2).

    estimate(window, state) -> {"tension": 0..5, "reason": ...}

The rule path is what the beats declare: the `tension` the played beats' effects have added up to. That is
exactly why it may not be used to evaluate the drama manager (backend-design.md §2 principle 5); the llm and
trained paths read the last turns instead. Offline the llm mock answers with the rule value.
"""

from __future__ import annotations

import json
from typing import Any

from engine.llm import LLMOutputError, extract_json, get_client
from engine.models.base import SlotRun, path_from_env, run_slot, shadow_from_env
from engine.models.prompts import system_prompt
from engine.paths import SCHEMAS_DIR

TENSION_SCHEMA = json.loads((SCHEMAS_DIR / "llm" / "tension.json").read_text(encoding="utf-8"))


class RuleTensionPath:
    path = "rule"

    async def estimate(self, window: list[str], state: dict[str, Any]) -> dict[str, Any]:
        return {"tension": float(state.get("tension", 1)), "reason": "sum of declared beat effects", "meta": {}, "fallback": False}


class LLMTensionPath:
    path = "llm"

    def __init__(self, temperature: float = 0.0):
        self.client = get_client("tension", temperature, mock_handler=self._mock)

    @staticmethod
    def _mock(system: str, user: str) -> dict[str, Any]:
        req = extract_json(user)
        return {"tension": float(req["declared_tension"]), "reason": "mock: declared tension"}

    async def estimate(self, window: list[str], state: dict[str, Any]) -> dict[str, Any]:
        prompt = system_prompt("tension")
        payload = {"window": window, "declared_tension": float(state.get("tension", 1))}
        user = f"Rate the tension of this window. Return only the JSON object.\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n```"
        try:
            res = await self.client.call_json(prompt.text, user, schema=TENSION_SCHEMA, prompt_version=prompt.version)
        except LLMOutputError as e:
            return {"tension": float(state.get("tension", 1)), "reason": "fallback: declared tension", "meta": e.result.meta(), "fallback": True}
        return {**res.data, "meta": res.meta(), "fallback": False}


class TrainedTensionPath:
    path = "trained"
    delegates = True

    def __init__(self, llm: LLMTensionPath):
        self.llm = llm

    async def estimate(self, window: list[str], state: dict[str, Any]) -> dict[str, Any]:
        out = await self.llm.estimate(window, state)
        return {**out, "meta": {**out["meta"], "delegated_to": "llm"}}


class TensionEstimator:
    def __init__(self, active: str | None = None, shadow: bool | None = None):
        llm = LLMTensionPath()
        self.paths = {"rule": RuleTensionPath(), "llm": llm, "trained": TrainedTensionPath(llm)}
        self.active = active or path_from_env("tension")
        self.shadow = shadow_from_env() if shadow is None else shadow

    async def estimate(self, window: list[str], state: dict[str, Any]) -> SlotRun:
        return await run_slot(
            self.paths, self.active, self.shadow,
            lambda p: p.estimate(window, state),
            lambda r, name: {**r, "meta": {**r["meta"], "delegated_to": "llm"}},
        )
