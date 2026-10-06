"""The three switchable scorers (docs/backend-design.md section 7).

All scorers share one interface:  score(ctx, candidates) -> list[ScoreResult]

    A  Façade handwritten:  weight * (1 + priority) * exp(-|slope_target - slope_beat|)
    B  LLM offset:          A's base weight + an integer offset (-5..+5) the frozen LLM assigns
                            per candidate with a one-line reason. Zero training. Also the dev-time
                            stand-in for C and the offline judge's cousin.
    C  Learned reward model (LoRA): NOT IMPLEMENTED in this version. `LearnedScorer` delegates to
                            B and tags its output so logs make the substitution visible.
    random                  uniform, for the report's floor.

The pseudo-candidate GENERATE_NEW is always present. A gives it a small constant unless nothing
else is eligible; B may lift it when no shelf beat fits (slides p13).
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Any

from engine.beats import GENERATE_NEW_ID, Beat, BeatPool
from engine.llm import get_client


@dataclass
class Candidate:
    beat: Beat | None  # None => GENERATE_NEW
    priority: float = 0.0

    @property
    def id(self) -> str:
        return self.beat.id if self.beat else GENERATE_NEW_ID

    @property
    def title(self) -> str:
        return self.beat.title if self.beat else "Generate a new beat (LLM)"

    @property
    def origin(self) -> str:
        return self.beat.origin if self.beat else "generated"

    @property
    def type(self) -> str:
        return self.beat.type if self.beat else "generated"

    @property
    def tension_slope(self) -> float:
        return self.beat.tension_slope if self.beat else 0.0

    def base_weight(self) -> float:
        w = self.beat.weight if self.beat else 1.0
        return w * (1.0 + self.priority)

    def text(self, eligible_best: str = "") -> str:
        if self.beat:
            return self.beat.text_for_scorer()
        return (
            "type=generated; slope=?; a brand-new beat the LLM would author now, fitting the current "
            "state; choose this only when no shelf beat above fits the moment."
        )


@dataclass
class ScoreResult:
    candidate_id: str
    score: float
    reason: str = ""


@dataclass
class ScoringContext:
    state: dict[str, Any]
    state_text: str
    target_slope: float
    decision_idx: int
    recent_dialogue: list[str] = field(default_factory=list)
    last_input: dict[str, Any] | None = None


def build_candidates(pool: BeatPool, state: dict[str, Any]) -> list[Candidate]:
    cands = [Candidate(beat=b, priority=pool.priority(b, state)) for b in pool.eligible(state)]
    cands.append(Candidate(beat=None))
    return cands


# ---------------------------------------------------------------------------
class HandwrittenScorer:
    id = "A"

    async def score(self, ctx: ScoringContext, cands: list[Candidate]) -> list[ScoreResult]:
        n_shelf = sum(1 for c in cands if c.beat)
        out = []
        for c in cands:
            if c.beat is None:
                s = 1.0 if n_shelf == 0 else 0.08
                out.append(ScoreResult(c.id, s, "fallback only" if n_shelf else "nothing eligible"))
                continue
            fit = math.exp(-abs(ctx.target_slope - c.tension_slope))
            out.append(ScoreResult(c.id, c.base_weight() * fit, f"fit={fit:.2f} target_slope={ctx.target_slope:+.0f}"))
        return out


class RandomScorer:
    id = "random"

    async def score(self, ctx: ScoringContext, cands: list[Candidate]) -> list[ScoreResult]:
        return [ScoreResult(c.id, random.random(), "random") for c in cands]


# ---------------------------------------------------------------------------
_SCORER_SYSTEM = """You are the drama manager of an interactive drama. Your job is to re-weight candidate beats
so the story follows its intended tension arc while staying coherent with what the player just did.
You never write dialogue here; you only judge which mini-scene should come next.

Return ONLY JSON of the form:
{"offsets": [{"id": "<candidate id>", "offset": <integer -5..5>, "reason": "<one short sentence>"}]}
Rules:
- Positive offset = this beat fits the moment and the arc. Negative = wrong moment, tone-deaf, or redundant.
- If NO shelf beat plausibly follows the player's last input, give GENERATE_NEW a high positive offset.
- Otherwise keep GENERATE_NEW at or below 0.
- Consider the target tension change: the arc wants tension to change by target_slope this beat."""


class LLMOffsetScorer:
    id = "B"

    def __init__(self, temperature: float = 0.2):
        self.client = get_client("scorer", temperature, mock_handler=_mock_scorer)

    async def score(self, ctx: ScoringContext, cands: list[Candidate]) -> list[ScoreResult]:
        listing = "\n".join(f"- id={c.id} | base_weight={c.base_weight():.2f} | {c.text()}" for c in cands)
        user = (
            f"STATE: {ctx.state_text}\n"
            f"TARGET_SLOPE: {ctx.target_slope:+.0f} (decision #{ctx.decision_idx})\n"
            f"RECENT_DIALOGUE:\n" + ("\n".join(ctx.recent_dialogue[-6:]) or "(none)") + "\n"
            f"LAST_PLAYER_INPUT: {json.dumps(ctx.last_input) if ctx.last_input else '(none)'}\n\n"
            f"CANDIDATES:\n{listing}"
        )
        try:
            data = await self.client.complete_json(_SCORER_SYSTEM, user)
            offsets = {o["id"]: o for o in data.get("offsets", []) if "id" in o}
        except Exception as e:  # noqa: BLE001 - scorer must never take the session down
            offsets = {}
            err = f"scorer B failed ({e.__class__.__name__}); using base weights"
        else:
            err = ""
        out = []
        for c in cands:
            o = offsets.get(c.id, {})
            off = float(o.get("offset", 0) or 0)
            off = max(-5.0, min(5.0, off))
            base = c.base_weight() if c.beat else 1.0
            out.append(ScoreResult(c.id, max(0.05, base + off), str(o.get("reason") or err)))
        return out


class LearnedScorer:
    """Placeholder for the LoRA reward model. Delegates to B; the substitution is visible in logs via
    `reason`. Replace `score` with the reward-model inference call when training lands (M4)."""

    id = "C"

    def __init__(self):
        self.inner = LLMOffsetScorer()

    async def score(self, ctx: ScoringContext, cands: list[Candidate]) -> list[ScoreResult]:
        res = await self.inner.score(ctx, cands)
        return [ScoreResult(r.candidate_id, r.score, f"[C=stub->B] {r.reason}") for r in res]


def _mock_scorer(system: str, user: str) -> dict[str, Any]:
    """Deterministic offline scorer: favours spine beats whose slope matches, keeps GENERATE_NEW low."""
    target = 0.0
    for line in user.splitlines():
        if line.startswith("TARGET_SLOPE:"):
            try:
                target = float(line.split(":")[1].split()[0])
            except ValueError:
                pass
    offsets = []
    for line in user.splitlines():
        if not line.startswith("- id="):
            continue
        cid = line.split("id=")[1].split(" |")[0].strip()
        if cid == GENERATE_NEW_ID:
            offsets.append({"id": cid, "offset": -3, "reason": "shelf beats fit; no need to improvise"})
            continue
        slope = 0.0
        if "slope=" in line:
            try:
                slope = float(line.split("slope=")[1].split(";")[0])
            except ValueError:
                pass
        is_spine = "type=spine" in line
        off = 2 if is_spine else 0
        off += 1 if abs(slope - target) < 0.5 else -1
        offsets.append({"id": cid, "offset": off, "reason": "mock: spine+slope heuristic"})
    return {"offsets": offsets}


def make_scorer(scorer_id: str):
    return {
        "A": HandwrittenScorer,
        "B": LLMOffsetScorer,
        "C": LearnedScorer,
        "random": RandomScorer,
    }[scorer_id]()
