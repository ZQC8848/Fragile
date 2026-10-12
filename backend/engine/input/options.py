"""Option generation (interaction-design.md §3.4): three moves in channel form, one per strategy.

    respond   answer what the scene is asking right now
    probe     follow a clue or topic the player already knows about
    social    side with, comfort or push back on someone

Generated only when the player asks. Options may only use what the player knows; the guard checks them like
narration before they are shown. The offline mock builds them from the situation with fixed phrasings.
"""

from __future__ import annotations

import json
from typing import Any

from engine.llm import LLMOutputError, extract_json, get_client
from engine.models import Guard, GuardContext
from engine.models.prompts import system_prompt
from engine.paths import SCHEMAS_DIR

OPTIONS_SCHEMA = json.loads((SCHEMAS_DIR / "llm" / "options.json").read_text(encoding="utf-8"))


def _opt(strategy: str, speech: str = "", action: str = "", expression: str = "", addressee: str | None = None) -> dict[str, Any]:
    return {"speech": speech, "action": action, "expression": expression, "addressee": addressee, "strategy": strategy}


def mock_options(req: dict[str, Any]) -> dict[str, Any]:
    present = [p for p in req["present"] if p in ("julian", "mia", "nora")]
    hosts = [p for p in present if p != "nora"]
    asks = req.get("asking") or {}
    last = req.get("last_speaker") if req.get("last_speaker") in present else (hosts[0] if hosts else (present[0] if present else None))
    revealed = set(req.get("revealed") or [])

    # respond
    if req.get("ringing"):
        respond = _opt("respond", action="I answer the phone.", addressee="nora")
    elif req.get("invite"):
        respond = _opt("respond", speech="Sure.", addressee=req["invite"]["asker"])
    elif asks.get("kind") == "side":
        asker = asks.get("asker")
        pick = asker if asker in ("julian", "mia") else ("julian" if req.get("side", 0) < 0 else "mia")
        respond = _opt("respond", speech=f"I think {pick.capitalize()} is right.", addressee=asker if asker in present else pick)
    elif asks.get("asker") == "nora" or "nora" in present:
        respond = _opt("respond", speech="I don't know where he is.", addressee="nora")
    elif last:
        respond = _opt("respond", speech="What do you mean?", addressee=last)
    else:
        respond = _opt("respond", expression="I wait.")

    # probe
    room = req.get("room")
    if "car_downstairs" in revealed and hosts:
        probe = _opt("probe", speech="Isn't that Leo's car downstairs?", addressee="both" if len(hosts) > 1 else hosts[0])
    elif req.get("player_phone") == "unchecked":
        probe = _opt("probe", action="I listen to the voicemail on my phone.")
    elif "crate" in req.get("can_see", []):
        probe = _opt("probe", action="I knock on the crate.")
    elif room == "balcony":
        probe = _opt("probe", action="I look down at the street.")
    elif hosts:
        probe = _opt("probe", speech="Where's Leo tonight?", addressee=hosts[0])
    else:
        probe = _opt("probe", action="I look around.")

    # social
    if hosts:
        target = min(hosts, key=lambda h: req.get("composure", {}).get(h, 1))
        social = _opt("social", speech="Are you okay?", addressee=target)
    elif "nora" in present:
        social = _opt("social", speech="We'll find him.", addressee="nora")
    else:
        social = _opt("social", expression="I take a breath.")
    return {"options": [respond, probe, social]}


class OptionGenerator:
    def __init__(self, guard: Guard, temperature: float = 0.7):
        self.guard = guard
        self.client = get_client("options", temperature, mock_handler=lambda s, u: mock_options(extract_json(u)))

    async def generate(self, req: dict[str, Any], guard_ctx: GuardContext) -> dict[str, Any]:
        prompt = system_prompt("options")
        user = f"Offer three options. Return only the JSON object.\n\n```json\n{json.dumps(req, ensure_ascii=False, indent=1)}\n```"
        try:
            res = await self.client.call_json(prompt.text, user, schema=OPTIONS_SCHEMA, prompt_version=prompt.version)
            options, meta, fallback = res.data["options"], res.meta(), False
        except LLMOutputError as e:
            options, meta, fallback = mock_options(req)["options"], e.result.meta(), True
        # options are the player's own words: check them as narration against what the player knows
        segs = [{"kind": "narration", "text": " ".join(filter(None, [o.get("speech"), o.get("action"), o.get("expression")]))} for o in options]
        verdicts = await self.guard.check(segs, guard_ctx)
        bad = {v["index"] for v in Guard.failures(verdicts.result["verdicts"])}
        kept = [o for i, o in enumerate(options) if i not in bad]
        return {"options": kept, "dropped": sorted(bad), "guard": verdicts.log(), "meta": meta, "fallback": fallback}
