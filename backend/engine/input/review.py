"""Input review before submit (interaction-design.md §3.3, §4): rule pre-check, then M2.

    review(turn_input, context) -> Review

Pre-check (§4.6 step 1): all empty is silence; overlong input; meta phrasing; an NPC as the subject of the
action channel. Whatever passes goes to the encoder, which splits, translates, validates, rewrites and
classifies in one go. Reviews are kept by id so an accepted draft can be submitted without classifying again.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from engine.models import Encoder, EncoderOutput, SlotRun
from engine.models.rule_encoder import VALIDITY_MESSAGES

MAX_CHARS = 1200
_META = re.compile(r"ignore (all |the |your |any )?(previous|prior|above|earlier)|system prompt|you are an ai|jailbreak|忽略之前", re.I)
_NPC_SUBJECT = re.compile(r"^\s*(julian|mia|nora)\s+(?!and\b)[a-z]+(s|ed)\b", re.I)


@dataclass
class Review:
    id: str
    turn_input: dict[str, Any]
    #: rule pre-check verdict, when it decided on its own
    precheck: str | None
    run: SlotRun | None
    #: silence: no channels at all
    silent: bool = False
    rejections_before: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def output(self) -> EncoderOutput | None:
        return self.run.result if self.run else None

    @property
    def validity(self) -> dict[str, Any]:
        if "validity" in self.extra:
            return self.extra["validity"]
        return self.output.validity if self.output else {"label": "ok"}

    @property
    def ok(self) -> bool:
        return self.validity.get("label") == "ok"

    @property
    def channels(self) -> dict[str, Any]:
        if self.output:
            return self.output.channels
        return dict(self.turn_input.get("channels") or {"speech": "", "action": "", "expression": "", "addressee": None})

    def message(self) -> dict[str, Any]:
        """The input_review_result message (schemas/messages_v2.json)."""
        v = self.validity
        msg: dict[str, Any] = {
            "type": "input_review_result",
            "review_id": self.id,
            "verdict": "ok" if self.ok else "rejected",
            "channels": _channels(self.channels),
            "translated": bool(self.output and self.output.data.get("translated")),
        }
        if not self.ok:
            msg["category"] = v["label"]
            if v.get("message"):
                msg["message"] = v["message"]
            if v.get("span"):
                msg["span"] = v["span"]
            rw = self.output.data.get("rewrite") if self.output else None
            msg["rewrite"] = _channels(rw) if rw else None
        return msg

    def public(self) -> dict[str, Any]:
        return {
            "review_id": self.id,
            "input": self.turn_input,
            "precheck": self.precheck,
            "silent": self.silent,
            "validity": self.validity,
            "encoder": self.run.log(lambda r: r.public()) if self.run else None,
        }


def _channels(ch: dict[str, Any]) -> dict[str, Any]:
    return {
        "speech": ch.get("speech") or "",
        "action": ch.get("action") or "",
        "expression": ch.get("expression") or "",
        "addressee": ch.get("addressee"),
    }


def is_empty(turn_input: dict[str, Any]) -> bool:
    if turn_input.get("mode") == "single":
        return not (turn_input.get("text") or "").strip()
    ch = turn_input.get("channels") or {}
    return not any((ch.get(k) or "").strip() for k in ("speech", "action", "expression"))


def precheck(turn_input: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """(verdict, validity) when the rules decide alone; (None, None) to go on to M2."""
    if is_empty(turn_input):
        return "silence", None
    ch = turn_input.get("channels") or {}
    text = turn_input.get("text") or " ".join(ch.get(k) or "" for k in ("speech", "action", "expression"))
    if len(text) > MAX_CHARS:
        return "too_long", {"label": "stride", "span": None, "message": f"That's more than one turn can hold (over {MAX_CHARS} characters)."}
    if m := _META.search(text):
        return "meta", {"label": "meta", "span": m.group(0), "message": VALIDITY_MESSAGES["meta"]}
    if turn_input.get("mode") != "single" and (m := _NPC_SUBJECT.search(ch.get("action") or "")):
        return "npc_action", {"label": "npc_action", "span": m.group(0), "message": VALIDITY_MESSAGES["npc_action"].format(span=m.group(0))}
    return None, None


class InputReviewer:
    def __init__(self, encoder: Encoder):
        self.encoder = encoder
        self.reviews: dict[str, Review] = {}

    async def review(self, turn_input: dict[str, Any], context: dict[str, Any]) -> Review:
        rid = uuid.uuid4().hex[:12]
        verdict, validity = precheck(turn_input)
        if verdict == "silence":
            empty = {"mode": "channels", "channels": {"speech": "", "action": "", "expression": "", "addressee": None}}
            run = await self.encoder.encode(empty, context)
            r = Review(rid, turn_input, verdict, run, silent=True)
        elif verdict is not None:
            r = Review(rid, turn_input, verdict, None, extra={"validity": validity})
        else:
            r = Review(rid, turn_input, None, await self.encoder.encode(turn_input, context))
        self.reviews[rid] = r
        return r

    def get(self, review_id: str | None) -> Review | None:
        return self.reviews.get(review_id or "")
