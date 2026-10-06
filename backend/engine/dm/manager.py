"""Drama Manager decision loop (docs/backend-design.md section 6).

    beat ends -> eligible + GENERATE_NEW -> score with A, B, C (all logged) -> sample with the
    active scorer -> Decision

Sampling keeps Façade's weighted random draw with a temperature:  p(b) ∝ score(b) ** (1/tau).
tau -> 0 is argmax (evaluation), tau = 1 is proportional (play).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

from engine.beats import GENERATE_NEW_ID, Beat, BeatPool
from engine.dm.scorers import (
    Candidate,
    HandwrittenScorer,
    LearnedScorer,
    LLMOffsetScorer,
    RandomScorer,
    ScoreResult,
    ScoringContext,
    build_candidates,
)
from engine.dm.tension import TensionArc


@dataclass
class CandidateReport:
    beat_id: str
    title: str
    origin: str
    type: str
    tension_slope: float
    scores: dict[str, float]
    reasons: dict[str, str]
    probability: float
    chosen: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "beat_id": self.beat_id,
            "title": self.title,
            "origin": self.origin,
            "type": self.type,
            "tension_slope": self.tension_slope,
            "scores": self.scores,
            "probability": round(self.probability, 4),
            "reason_B": self.reasons.get("B", ""),
            "reason_A": self.reasons.get("A", ""),
            "reason_C": self.reasons.get("C", ""),
            "chosen": self.chosen,
        }


@dataclass
class Decision:
    decision_idx: int
    candidates: list[CandidateReport]
    chosen_id: str
    scorer_used: str
    tau: float
    target_slope: float
    reasoning: str
    chosen_beat: Beat | None = None  # None => GENERATE_NEW
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_generate(self) -> bool:
        return self.chosen_id == GENERATE_NEW_ID


class DramaManager:
    def __init__(self, pool: BeatPool, arc: TensionArc, scorer_id: str = "B", tau: float = 1.0, seed: int | None = None):
        self.pool = pool
        self.arc = arc
        self.scorer_id = scorer_id
        self.tau = tau
        self.rng = random.Random(seed)
        self.scorers = {
            "A": HandwrittenScorer(),
            "B": LLMOffsetScorer(),
            "C": LearnedScorer(),
            "random": RandomScorer(),
        }

    def set_scorer(self, scorer_id: str) -> None:
        if scorer_id not in self.scorers:
            raise ValueError(f"unknown scorer {scorer_id!r}")
        self.scorer_id = scorer_id

    def set_tau(self, tau: float) -> None:
        self.tau = max(0.01, float(tau))

    async def decide(
        self,
        state: dict[str, Any],
        state_text: str,
        decision_idx: int,
        recent_dialogue: list[str],
        last_input: dict[str, Any] | None,
        force_beat_id: str | None = None,
    ) -> Decision:
        cands = build_candidates(self.pool, state)
        ctx = ScoringContext(
            state=state,
            state_text=state_text,
            target_slope=self.arc.target_slope(decision_idx),
            decision_idx=decision_idx,
            recent_dialogue=recent_dialogue,
            last_input=last_input,
        )

        # Score with every scorer so each decision produces comparison data for all experiments.
        results: dict[str, dict[str, ScoreResult]] = {}
        for sid in ("A", "B", "C"):
            res = await self.scorers[sid].score(ctx, cands)
            results[sid] = {r.candidate_id: r for r in res}
        if self.scorer_used_needs_random():
            res = await self.scorers["random"].score(ctx, cands)
            results["random"] = {r.candidate_id: r for r in res}

        active = results[self.scorer_id]
        probs = self._probabilities([active[c.id].score for c in cands])
        reports = [
            CandidateReport(
                beat_id=c.id,
                title=c.title,
                origin=c.origin,
                type=c.type,
                tension_slope=c.tension_slope,
                scores={sid: round(results[sid][c.id].score, 4) for sid in ("A", "B", "C")},
                reasons={sid: results[sid][c.id].reason for sid in ("A", "B", "C")},
                probability=p,
            )
            for c, p in zip(cands, probs, strict=True)
        ]

        if force_beat_id and any(c.id == force_beat_id for c in cands):
            chosen_id = force_beat_id
            reasoning = f"forced by console: {force_beat_id}"
        elif force_beat_id and force_beat_id in self.pool.by_id:
            # Console may force an ineligible beat: honor it, but say so.
            chosen_id = force_beat_id
            reasoning = f"forced by console (ineligible!): {force_beat_id}"
            cands.append(Candidate(beat=self.pool.by_id[force_beat_id]))
            reports.append(
                CandidateReport(force_beat_id, self.pool.by_id[force_beat_id].title, "authored", "forced", 0.0, {}, {}, 0.0)
            )
        else:
            chosen_id = self._sample([c.id for c in cands], probs)
            top = max(reports, key=lambda r: r.probability)
            reasoning = (
                f"scorer {self.scorer_id}, tau={self.tau:.2f}, target_slope={ctx.target_slope:+.0f}; "
                f"top={top.beat_id} p={top.probability:.2f}; chosen={chosen_id}; "
                f"why: {active[chosen_id].reason}"
            )
        for r in reports:
            r.chosen = r.beat_id == chosen_id
        chosen_beat = next((c.beat for c in cands if c.id == chosen_id), None)
        return Decision(
            decision_idx=decision_idx,
            candidates=reports,
            chosen_id=chosen_id,
            scorer_used=self.scorer_id,
            tau=self.tau,
            target_slope=ctx.target_slope,
            reasoning=reasoning,
            chosen_beat=chosen_beat,
        )

    def scorer_used_needs_random(self) -> bool:
        return self.scorer_id == "random"

    def _probabilities(self, scores: list[float]) -> list[float]:
        inv = 1.0 / max(self.tau, 0.01)
        weights = [max(s, 1e-6) ** inv for s in scores]
        total = sum(weights)
        return [w / total for w in weights]

    def _sample(self, ids: list[str], probs: list[float]) -> str:
        if self.tau <= 0.05:
            return ids[max(range(len(probs)), key=lambda i: probs[i])]
        return self.rng.choices(ids, weights=probs, k=1)[0]
