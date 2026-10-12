"""Drama Manager decision (interaction-design.md §6.5, backend-design.md §3.1).

    beat ends ->  console force?                      -> that beat
              ->  a must-follow beat triggered?        -> the lowest rank, no scoring
              ->  testimony done?                      -> the ending table (lowest ending_rank)
              ->  eligible beats, highest priority tier only (Façade), + GENERATE_NEW
                  -> score with the active scorer (all paths in shadow mode) -> sample with temperature
              ->  nothing eligible                     -> kind "empty": the session fast-forwards the clock
                                                          or, with no clock event pending, generates a beat

Sampling keeps Façade's weighted random draw with a temperature: p(b) ∝ score(b) ** (1/tau). tau -> 0 is
argmax (evaluation), tau = 1 is proportional (play).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from engine.beats import GENERATE_NEW_ID, Beat, BeatPool, rule_ctx
from engine.clock import StoryClock
from engine.dm.tension import TensionArc
from engine.models.scorer import LETTER, Candidate, ScoreResult, ScoringContext, make_scorers

#: after this many generated beats in a row, GENERATE_NEW leaves the candidate list (convergence rule)
MAX_CONSECUTIVE_GENERATED = 2


@dataclass
class Decision:
    decision_idx: int
    #: forced | must_follow | ending | scored | generate | empty
    kind: str
    chosen_beat: Beat | None = None
    entry: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    scorer_used: str = ""
    tau: float = 1.0
    tier: float | None = None
    reasoning: str = ""

    @property
    def chosen_id(self) -> str | None:
        if self.kind == "generate":
            return GENERATE_NEW_ID
        return self.chosen_beat.id if self.chosen_beat else None

    def public(self) -> dict[str, Any]:
        return {
            "decision_idx": self.decision_idx,
            "kind": self.kind,
            "chosen": self.chosen_id,
            "entry": self.entry.get("id") if self.entry else None,
            "scorer": self.scorer_used,
            "tau": self.tau,
            "tier": self.tier,
            "reasoning": self.reasoning,
            "candidates": self.candidates,
        }


class DramaManager:
    def __init__(
        self,
        pool: BeatPool,
        arc: TensionArc,
        clock: StoryClock,
        scorer: str = "llm",
        tau: float = 1.0,
        seed: int | None = None,
        shadow: bool = False,
    ):
        self.pool = pool
        self.arc = arc
        self.clock = clock
        self.scorers = make_scorers(seed)
        self.scorer = scorer
        self.tau = tau
        self.shadow = shadow
        self.rng = random.Random(seed)
        self.set_scorer(scorer)

    def set_scorer(self, scorer: str) -> None:
        scorer = {"A": "rule", "B": "llm", "C": "trained"}.get(scorer, scorer)
        if scorer not in self.scorers:
            raise ValueError(f"unknown scorer {scorer!r}")
        self.scorer = scorer

    def set_tau(self, tau: float) -> None:
        self.tau = max(0.01, float(tau))

    # -- the decision ---------------------------------------------------------------------------
    async def decide(
        self,
        state: dict[str, Any],
        turn: dict[str, Any],
        *,
        decision_idx: int,
        state_text: str,
        tension: float,
        recent_dialogue: list[str] | None = None,
        last_input: dict[str, Any] | None = None,
        exclude: str | None = None,
        force_beat_id: str | None = None,
    ) -> Decision:
        ctx = rule_ctx(state, turn)
        if force_beat_id and force_beat_id in self.pool.by_id:
            beat = self.pool.by_id[force_beat_id]
            entry = self.pool.entry_for(beat, ctx) or beat.entries[0]
            eligible = self.pool.why_not(beat, state, turn) == ""
            return Decision(decision_idx, "forced", beat, entry, reasoning=f"forced by console{'' if eligible else ' (ineligible!)'}")

        must = self.pool.must_follow(state, turn, exclude=exclude)
        if must is not None:
            return Decision(decision_idx, "must_follow", must, self.pool.entry_for(must, ctx),
                            reasoning=f"must-follow rank {must.must_follow_rank}")

        ending = self.pool.ending_after_testimony(state, turn)
        if ending is not None:
            return Decision(decision_idx, "ending", ending, self.pool.entry_for(ending, ctx),
                            reasoning=f"ending table rank {ending.ending_rank}")

        cands = self.candidates(state, turn, exclude, tension)
        if not cands:
            return Decision(decision_idx, "empty", reasoning="no eligible beat")
        tier = max(c.priority for c in cands)
        cands = [c for c in cands if c.priority == tier]
        if state.get("consecutive_generated", 0) < MAX_CONSECUTIVE_GENERATED:
            cands.append(Candidate(beat=None, priority=0.0))

        sctx = ScoringContext(state, state_text, decision_idx, tension, recent_dialogue or [], last_input)
        results: dict[str, dict[str, ScoreResult]] = {}
        for path in self.scorers if self.shadow else [self.scorer]:
            res = await self.scorers[path].score(sctx, cands)
            results[path] = {r.candidate_id: r for r in res}
        active = results[self.scorer]
        probs = self._probabilities([active[c.id].score for c in cands])
        chosen_id = self._sample([c.id for c in cands], probs)
        reports = [
            {
                "beat_id": c.id,
                "title": c.title,
                "type": c.type,
                "origin": c.origin,
                "priority": c.priority,
                "entry": c.entry.get("id") if c.entry else None,
                "tension_slope": c.tension_slope,
                "target_slope": round(c.target_slope, 2),
                "scores": {LETTER[p]: round(r[c.id].score, 4) for p, r in results.items()},
                "reasons": {LETTER[p]: r[c.id].reason for p, r in results.items()},
                "probability": round(p, 4),
                "chosen": c.id == chosen_id,
            }
            for c, p in zip(cands, probs, strict=True)
        ]
        chosen = next(c for c in cands if c.id == chosen_id)
        top = max(reports, key=lambda r: r["probability"])
        reasoning = (
            f"scorer {LETTER[self.scorer]}, tau={self.tau:.2f}, tier={tier:g}; top={top['beat_id']} "
            f"p={top['probability']:.2f}; chosen={chosen_id}; why: {active[chosen_id].reason}"
        )
        kind = "generate" if chosen.beat is None else "scored"
        return Decision(decision_idx, kind, chosen.beat, chosen.entry, reports, LETTER[self.scorer], self.tau, tier, reasoning)

    def candidates(self, state: dict[str, Any], turn: dict[str, Any], exclude: str | None, tension: float) -> list[Candidate]:
        """Eligible non-ending beats with their entry, priority and target slope."""
        ctx = rule_ctx(state, turn)
        out = []
        for b in self.pool.eligible(state, turn):
            if b.is_ending or b.id == exclude:
                continue
            entry = self.pool.entry_for(b, ctx)
            minutes = self.clock.minutes_for(b.minutes, float(state.get("story_min", 0)))
            # tension effects are slope x 0.5 (beat-script.md §5 rule 1), so compare in slope units
            target = self.arc.target_delta(float(state.get("story_min", 0)), minutes, tension) / 0.5
            out.append(Candidate(beat=b, priority=self.pool.priority(b, ctx, entry), entry=entry, target_slope=target))
        return out

    async def rank(
        self,
        state: dict[str, Any],
        turn: dict[str, Any],
        beats: list[Beat],
        *,
        decision_idx: int,
        state_text: str,
        tension: float,
        recent_dialogue: list[str] | None = None,
    ) -> tuple[Beat, dict[str, float]]:
        """Generated drafts ranked by the active scorer (M1 replaces the judge at runtime); argmax."""
        ctx = rule_ctx(state, turn)
        story_min = float(state.get("story_min", 0))
        cands = [
            Candidate(beat=b, priority=self.pool.priority(b, ctx, self.pool.entry_for(b, ctx)), entry=self.pool.entry_for(b, ctx),
                      target_slope=self.arc.target_delta(story_min, self.clock.minutes_for(b.minutes, story_min), tension) / 0.5)
            for b in beats
        ]
        if len(cands) == 1:
            return beats[0], {beats[0].id: 1.0}
        sctx = ScoringContext(state, state_text, decision_idx, tension, recent_dialogue or [], None)
        res = await self.scorers[self.scorer].score(sctx, cands)
        scores = {r.candidate_id: round(r.score, 4) for r in res}
        best = max(cands, key=lambda c: scores[c.id])
        return best.beat, scores

    def best_authored(self, decision: Decision) -> Beat | None:
        """The most probable shelf beat of a scored decision (the fallback when generation fails)."""
        shelf = [c for c in decision.candidates if c["beat_id"] != GENERATE_NEW_ID]
        if not shelf:
            return None
        return self.pool.by_id[max(shelf, key=lambda c: c["probability"])["beat_id"]]

    # -- sampling ----------------------------------------------------------------------------------
    def _probabilities(self, scores: list[float]) -> list[float]:
        inv = 1.0 / max(self.tau, 0.01)
        weights = [max(s, 1e-6) ** inv for s in scores]
        total = sum(weights)
        return [w / total for w in weights]

    def _sample(self, ids: list[str], probs: list[float]) -> str:
        if self.tau <= 0.05:
            return ids[max(range(len(probs)), key=lambda i: probs[i])]
        return self.rng.choices(ids, weights=probs, k=1)[0]
