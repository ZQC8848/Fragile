"""A beat being played: step pointer, step planning, asking steps, invitations, outcomes.

The engine, not the narrator, moves the step pointer (plan.md §3.1, P4): before the narrator writes, the
runner decides which steps this turn must deliver, so the drama manager can pick the next beat in the same
turn and its opening goes into the same passage.

Turn accounting: the turn that picks a beat only stages its opening. Every later turn inside the beat
counts toward `max_turns`. A question thrown on the last allowed turn still gets its answer turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.beats.loader import Beat
from engine.dsl import truthy

#: a primary reaction of these types takes the turn: no step is delivered, the thread resumes next turn
#: (interaction-design.md §6.2 "逼过头"). plan.md §3.1 writes this as "priority >= 8", but that would also stop the
#: beat for every local mix-in (10) and every blocked action (9), which are meant to be answered in passing.
INTERRUPT_TYPES = frozenset({"push_too_far"})

_PRO = {"agree", "praise", "comfort", "promise_silence", "thank"}
_CON = {"disagree", "criticize", "provoke", "refuse"}


@dataclass
class BeatRun:
    beat: Beat
    entry: dict[str, Any]
    #: index of the next undelivered step (state.beat_step)
    step: int = 0
    #: turns played inside the beat, the opening turn excluded (state.beat_turns)
    turns: int = 0
    #: id of the asking step whose answer is the next input
    awaiting: str | None = None
    #: the opening was an invitation the player has not answered yet
    invite_pending: bool = False
    outcome: str | None = None
    started_turn: int = 0
    #: the last turn delivered no step because a big reaction took it; the next steps pick the thread back up
    interrupted: bool = False

    @classmethod
    def start(cls, beat: Beat, entry: dict[str, Any], turn_no: int) -> BeatRun:
        return cls(beat=beat, entry=entry, invite_pending=bool(entry.get("invite")), started_turn=turn_no)

    # -- views -------------------------------------------------------------------
    @property
    def remaining(self) -> list[dict[str, Any]]:
        return self.beat.steps[self.step :]

    @property
    def finished(self) -> bool:
        return self.step >= len(self.beat.steps) and self.awaiting is None and not self.invite_pending

    def asking_step(self) -> dict[str, Any] | None:
        return next((s for s in self.beat.steps if s["id"] == self.awaiting), None)

    def public(self) -> dict[str, Any]:
        return {
            "beat_id": self.beat.id,
            "entry": self.entry.get("id"),
            "step": self.step,
            "steps": [s["id"] for s in self.beat.steps],
            "turns": self.turns,
            "max_turns": self.beat.max_turns,
            "awaiting": self.awaiting,
            "invite_pending": self.invite_pending,
            "outcome": self.outcome,
        }

    # -- planning ------------------------------------------------------------------
    def plan(self, interrupted: bool = False, force_all: bool = False) -> list[dict[str, Any]]:
        """Steps the narrator must deliver this turn. Call after `turns` counts this turn.

        One step per turn by default; more when the steps left would not fit in the turns left; all of them
        on the last allowed turn. A big reaction (`interrupted`) takes the turn instead, except on the last
        turn. Planning stops after an asking step: its answer is the next input."""
        remaining = self.remaining
        if not remaining or self.awaiting or self.invite_pending:
            return []
        turns_left = self.beat.max_turns - self.turns + 1
        last_turn = force_all or turns_left <= 1
        if last_turn:
            n = len(remaining)
        elif interrupted:
            n = 0
        else:
            n = max(1, len(remaining) - turns_left + 1)
        out: list[dict[str, Any]] = []
        for s in remaining[:n]:
            out.append(s)
            if s.get("asks"):
                break
        return out

    def deliver(self, steps: list[dict[str, Any]]) -> None:
        self.step += len(steps)
        if steps and steps[-1].get("asks"):
            self.awaiting = steps[-1]["id"]

    # -- answers -------------------------------------------------------------------
    def choose_outcome(self, ctx: dict[str, Any]) -> dict[str, Any] | None:
        """The outcome the player's answer leads to (interaction-design.md §6.3). ctx carries `turn`."""
        step = self.asking_step()
        if step is None or not self.beat.outcomes:
            return None
        asks = step["asks"]
        turn = ctx.get("turn") or {}
        by_id = {o["id"]: o for o in self.beat.outcomes}
        silence = by_id.get(asks.get("on_silence") or "")
        if turn.get("silent") and silence:
            return silence
        if asks["kind"] == "side":
            # M2 reads the whole answer ("I'll be kind to her, but I won't promise you that"); the act rules
            # only stand in when it gave no verdict (plan.md R23)
            side = turn.get("side_answer") or side_answer(asks["asker"], turn)
            if side in by_id:
                return by_id[side]
            return by_id.get("neutral") or silence or self.beat.outcomes[-1]
        for outcome, rule in zip(self.beat.outcomes, self.beat.compiled["outcomes"], strict=True):
            if rule is None or truthy(rule, ctx):
                return outcome
        return silence or self.beat.outcomes[-1]

    def answer(self, outcome: dict[str, Any] | None) -> None:
        self.outcome = outcome["id"] if outcome else None
        self.awaiting = None


def side_answer(asker: str, turn: dict[str, Any]) -> str | None:
    """Which host the player's answer to a side question backs: supporting one, or going against the other
    (interaction-design.md §5.4). A bare yes or no counts toward or against the asker."""
    acts = set(turn.get("acts") or [])
    addr = turn.get("addressee")
    score = {"julian": 0, "mia": 0}
    for host, other in (("julian", "mia"), ("mia", "julian")):
        if acts & _PRO and addr == host:
            score[host] += 1
        if acts & _CON and addr == other:
            score[host] += 1
        if f"accuse_{other}" in acts:
            score[host] += 1
    if asker in score and addr in (None, "both", "self", asker):
        if acts & _PRO:
            score[asker] += 1
        if acts & _CON and addr in (None, "both", "self"):
            score["mia" if asker == "julian" else "julian"] += 1
    best = max(score, key=lambda k: score[k])
    if score[best] == 0 or score["julian"] == score["mia"]:
        return None
    return best


def accepts_invite(invite: dict[str, Any], turn: dict[str, Any]) -> bool:
    """Saying no, or walking somewhere else, refuses; anything else goes along."""
    acts = set(turn.get("acts") or [])
    if acts & {"refuse", "disagree", "leave"}:
        return False
    action = turn.get("action") or {}
    if action.get("verb") == "leave":
        return False
    if action.get("verb") == "go_to" and action.get("target") != invite["to_room"]:
        return False
    return True
