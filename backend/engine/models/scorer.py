"""M1, the beat scorer, behind one interface with three paths (backend-design.md §4.1, §7.2).

    score(ctx, candidates) -> list[ScoreResult]

    rule     A  Façade handwritten: weight * (1 + priority) * exp(-|target_slope - slope|)
    llm      B  A's base weight + an integer offset (-5..+5) a frozen LLM assigns per candidate
    trained  C  the LoRA reward model; until it exists it delegates to B and says so in `reason`
    random      uniform, the report's floor

The target slope is per candidate: the tension arc is indexed by story minutes, so a 1.5-minute beat and a
1-minute beat aim at different points on it (data/tension_curve.yaml). The pseudo-candidate GENERATE_NEW is
present unless the convergence rule removed it.
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from typing import Any

from engine.beats import GENERATE_NEW_ID, Beat
from engine.llm import LLMOutputError, get_client
from engine.models.prompts import BUILTIN_V0, system_prompt
from engine.paths import SCHEMAS_DIR

SCORER_SCHEMA = json.loads((SCHEMAS_DIR / "llm" / "scorer.json").read_text(encoding="utf-8"))

#: scorer letters used in logs and the Console, by path
LETTER = {"rule": "A", "llm": "B", "trained": "C", "random": "random"}


@dataclass
class Candidate:
    beat: Beat | None  # None => GENERATE_NEW
    priority: float = 0.0
    entry: dict[str, Any] | None = None
    #: desired tension change, in slope units, if this beat is played now
    target_slope: float = 0.0

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

    def text(self) -> str:
        if self.beat:
            entry = f" entry: {self.entry['opening']}" if self.entry else ""
            return self.beat.text_for_scorer() + entry
        return (
            "type=generated; slope=?; a brand-new beat the LLM would author now, fitting the current state; "
            "choose this only when no shelf beat above fits the moment."
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
    decision_idx: int
    tension: float
    recent_dialogue: list[str] = field(default_factory=list)
    last_input: dict[str, Any] | None = None


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
            fit = math.exp(-abs(c.target_slope - c.tension_slope))
            out.append(ScoreResult(c.id, c.base_weight() * fit, f"fit={fit:.2f} target_slope={c.target_slope:+.1f}"))
        return out


class RandomScorer:
    id = "random"

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    async def score(self, ctx: ScoringContext, cands: list[Candidate]) -> list[ScoreResult]:
        return [ScoreResult(c.id, self.rng.random(), "random") for c in cands]


_SCORER_SYSTEM = """You are the drama manager of an interactive drama. Re-weight candidate beats so the story follows
its intended tension arc while staying coherent with what the player just did. You never write dialogue here; you
only judge which mini-scene should come next.

Return ONLY JSON of the form:
{"offsets": [{"id": "<candidate id>", "offset": <integer -5..5>, "reason": "<one short sentence>"}]}
Rules:
- Positive offset = this beat fits the moment and the arc. Negative = wrong moment, tone-deaf, or redundant.
- If NO shelf beat plausibly follows the player's last input, give GENERATE_NEW a high positive offset.
- Otherwise keep GENERATE_NEW at or below 0.
- Each candidate has a target_slope: the tension change the arc wants if that beat is played now."""
BUILTIN_V0.setdefault("scorer", _SCORER_SYSTEM)


class LLMOffsetScorer:
    id = "B"

    def __init__(self, temperature: float = 0.2):
        self.client = get_client("scorer", temperature, mock_handler=_mock_scorer)
        self.last_meta: dict[str, Any] = {}

    async def score(self, ctx: ScoringContext, cands: list[Candidate]) -> list[ScoreResult]:
        listing = "\n".join(
            f"- id={c.id} | base_weight={c.base_weight():.2f} | target_slope={c.target_slope:+.1f} | {c.text()}" for c in cands
        )
        user = (
            f"STATE: {ctx.state_text}\n"
            f"MEASURED_TENSION: {ctx.tension:.2f} (decision #{ctx.decision_idx})\n"
            "RECENT_DIALOGUE:\n" + ("\n".join(ctx.recent_dialogue[-6:]) or "(none)") + "\n"
            f"LAST_PLAYER_INPUT: {json.dumps(ctx.last_input, ensure_ascii=False) if ctx.last_input else '(none)'}\n\n"
            f"CANDIDATES:\n{listing}"
        )
        err = ""
        try:
            prompt = system_prompt("scorer")
            res = await self.client.call_json(prompt.text, user, schema=SCORER_SCHEMA, prompt_version=prompt.version)
            offsets = {o["id"]: o for o in res.data.get("offsets", [])}
            self.last_meta = res.meta()
        except LLMOutputError as e:
            offsets = {}
            self.last_meta = e.result.meta()
            err = "scorer B output unusable; base weights"
        out = []
        for c in cands:
            o = offsets.get(c.id, {})
            off = max(-5.0, min(5.0, float(o.get("offset", 0) or 0)))
            base = c.base_weight() if c.beat else 1.0
            out.append(ScoreResult(c.id, max(0.05, base + off), str(o.get("reason") or err)))
        return out


class LearnedScorer:
    """Placeholder for the LoRA reward model. Delegates to B; `reason` makes the substitution visible."""

    id = "C"
    delegates = True

    def __init__(self, inner: LLMOffsetScorer):
        self.inner = inner

    async def score(self, ctx: ScoringContext, cands: list[Candidate]) -> list[ScoreResult]:
        res = await self.inner.score(ctx, cands)
        return [ScoreResult(r.candidate_id, r.score, f"[C=stub->B] {r.reason}") for r in res]


def _mock_scorer(system: str, user: str) -> dict[str, Any]:
    """Deterministic offline scorer: favours spine beats whose slope matches their target, keeps GENERATE_NEW low."""
    offsets = []
    for line in user.splitlines():
        if not line.startswith("- id="):
            continue
        cid = line.split("id=")[1].split(" |")[0].strip()
        if cid == GENERATE_NEW_ID:
            offsets.append({"id": cid, "offset": -3, "reason": "shelf beats fit; no need to improvise"})
            continue
        target = float(line.split("target_slope=")[1].split()[0])
        slope = float(line.split("slope=", 2)[2].split(";")[0]) if line.count("slope=") >= 2 else 0.0
        off = (2 if "type=spine" in line else 0) + (1 if abs(slope - target) < 1 else -1)
        offsets.append({"id": cid, "offset": off, "reason": "mock: spine+slope heuristic"})
    return {"offsets": offsets}


def make_scorers(seed: int | None = None) -> dict[str, Any]:
    """{path: scorer} for the DM: rule=A, llm=B, trained=C, random."""
    b = LLMOffsetScorer()
    return {"rule": HandwrittenScorer(), "llm": b, "trained": LearnedScorer(b), "random": RandomScorer(seed)}
