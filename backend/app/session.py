"""One play session: the turn loop (plan.md §3.1, interaction-design.md §2).

    review   = M2 on the input (reused when the player sends the reviewed draft unchanged)
    turn     = the transient namespace rules read (acts, addressee, topics, claims, action, ...)
    world    = the action attempt lands: done / failed / blocked; hosts follow; private_turns
    reaction = rules + one primary reaction + at most one secondary; the answer to an asking step picks the
               beat's outcome; every variable moves at most one step this turn
    plan     = the steps this turn delivers (none when a big reaction takes the turn)
    if the beat ends (all steps delivered and answered, a must-follow beat triggered, or refused):
        story_min += its minutes; crossed clock events fire; unless the call event holds the choice, the DM
        picks the next beat now (fast-forwarding the clock over gaps, generating when nothing is pending)
    narrator writes the passage -> guard checks it, rewrite at most twice, then repair
    log the turn; push passage, room, phone, Console state

The session talks to the outside through one `push(message)` coroutine: the WebSocket, the terminal client
and the tests all drive the same object. Messages follow schemas/messages_v2.json.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any

import yaml

import engine.journal.decisions as _journal
from engine.beats import INTERRUPT_TYPES, BeatPool, BeatRun, accepts_invite, rule_ctx
from engine.clock import ClockEvent, StoryClock
from engine.dm import Decision, DramaManager, TensionArc
from engine.dsl import apply_effects
from engine.generate import Proposer
from engine.illustrate import pick_tableau
from engine.input import InputReviewer, OptionGenerator, Review, build_turn, is_empty
from engine.journal import SessionLogger
from engine.llm import CALL_LOG, set_llm_live
from engine.llm.client import _clients
from engine.models import Encoder, Guard, GuardContext, TensionEstimator, path_from_env, shadow_from_env
from engine.models.encoder import empty_output
from engine.narrator import Knowledge, NarrationRequest, Narrator, fill, repair
from engine.narrator import ledger as story_ledger
from engine.paths import DATA_DIR
from engine.reactions import ReactionLayer
from engine.state import StateSchema
from engine.world import WorldResult, WorldRules

Push = Callable[[dict[str, Any]], Awaitable[None]]

NPCS = ("julian", "mia", "nora")
MAX_GUARD_REWRITES = 2
TENSION_WINDOW = 4
#: seconds one turn may spend on narration, rewrites included (NARRATOR_TURN_BUDGET_S overrides)
NARRATION_BUDGET_S = 150.0


async def _discard(_: dict[str, Any]) -> None:
    return None


class SessionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Session:
    def __init__(
        self,
        session_id: str,
        push: Push | None = None,
        *,
        seed: int | None = None,
        scorer: str | None = None,
        tau: float = 1.0,
        log_root=None,
        save_generated: bool = True,
    ):
        self.id = session_id
        self.push = push or _discard
        self.schema = StateSchema()
        self.clock = StoryClock.from_file()
        self.pool = BeatPool.from_dir(DATA_DIR / "beats", set(self.schema.props))
        self.world = WorldRules.from_file(self.schema)
        self.reactions = ReactionLayer.from_file()
        self.knowledge = Knowledge.from_dir()
        self.prologue = (DATA_DIR / "prologue.txt").read_text(encoding="utf-8").strip()
        self.tableaux: dict[str, Any] = yaml.safe_load((DATA_DIR / "tableaux.yaml").read_text(encoding="utf-8"))
        shadow = shadow_from_env()
        self.encoder = Encoder(self.world.object_topics(), shadow=shadow, action_table=self.world.action_table())
        self.guard = Guard(shadow=shadow)
        self.tension = TensionEstimator(shadow=shadow)
        self.dm = DramaManager(self.pool, TensionArc.from_file(), self.clock, scorer or path_from_env("scorer"), tau, seed, shadow)
        self.narrator = Narrator()
        self.reviewer = InputReviewer(self.encoder)
        self.options = OptionGenerator(self.guard)
        self.proposer = Proposer(self.schema, self.clock, save=save_generated)
        self.logger = SessionLogger(session_id, log_root or _journal.LOGS_DIR)
        self.lock = asyncio.Lock()
        self._reset_runtime()

    def _reset_runtime(self) -> None:
        self.phase = "lobby"
        self.name = ""
        self.gender = "female"
        self.state: dict[str, Any] = self.schema.initial_state()
        self.run: BeatRun | None = None
        self.used: set[str] = set()
        self.turns: list[dict[str, Any]] = []
        self.suspicion: list[float] = []
        self.last_speaker: str | None = None
        self.passages: list[dict[str, Any]] = []
        self.phone: list[dict[str, Any]] = []
        self.tension_measured = float(self.state["tension"])
        self.tension_trace: list[dict[str, Any]] = []
        self._tension_task: asyncio.Task | None = None
        self.decision_idx = 0
        self.force_beat: str | None = None
        self.rejections = 0
        self.last_options: dict[str, Any] | None = None
        self.options_requests = 0
        self.traces: list[dict[str, Any]] = []
        self.last_decision: Decision | None = None
        self.card: dict[str, Any] | None = None
        #: tableaux already shown this session: each illustrated moment appears once
        self.shown_tableaux: set[str] = set()

    # ===================================================================== public entry points
    async def start(self, name: str, gender: str) -> None:
        calls: list[dict[str, Any]] = []
        token = CALL_LOG.set(calls)
        try:
            await self._start(name, gender, calls)
        finally:
            CALL_LOG.reset(token)

    async def _start(self, name: str, gender: str, calls: list[dict[str, Any]]) -> None:
        async with self.lock:
            self._reset_runtime()
            self.logger.reset()
            self.name, self.gender = name.strip() or "Sam", gender
            self.phase = "playing"
            await self.push({"type": "session_state", "phase": "playing", "turn": 0})
            self.card = {"type": "player_card", "name": self.name, **self.knowledge.player_card(self.state)}
            await self.push(self.card)
            for ev in (
                {"kind": "missed_call", "from": "leo", "text": "15:10", "id": "leo_missed_1"},
                {"kind": "missed_call", "from": "leo", "text": "15:10", "id": "leo_missed_2"},
                {"kind": "voicemail", "from": "leo", "id": "leo_voicemail"},
            ):
                await self._phone(ev)
            t0 = time.perf_counter()
            state = self.state
            decision = await self._decide(state, {})
            opening = self._start_beat(decision, 0)
            req = self._request(state, 0, prologue=self.prologue, opening=opening)
            out, guard_log = await self._narrate(req, state, None, [], [])
            await self._emit_passage(0, None, out["segments"], None, False)
            record = {
                "turn": 0, "session": self.id, "name_len": len(self.name), "gender": self.gender,
                "decision": decision.public(), "narrator": out, "guard": guard_log, "state": deepcopy(self.state),
                "latency_ms": {"total": round((time.perf_counter() - t0) * 1000, 1)}, "llm_calls": calls,
                "model_versions": self._model_versions(),
            }
            await self._finish_turn(record)

    async def review(self, turn_input: dict[str, Any]) -> Review:
        """Pre-submit check; never uses up a turn."""
        self._require_playing()
        calls: list[dict[str, Any]] = []
        token = CALL_LOG.set(calls)
        try:
            r = await self.reviewer.review(turn_input, self._encoder_context())
        finally:
            CALL_LOG.reset(token)
        r.extra["llm_calls"] = calls
        if not r.ok:
            self.rejections += 1
        self.logger.event("review", r.public())
        await self.push(r.message())
        return r

    async def submit(
        self,
        channels: dict[str, Any],
        source: str = "filled",
        review_id: str | None = None,
        injected: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Play one turn. Returns the turn record, or None when the input was rejected (no turn used)."""
        self._require_playing()
        async with self.lock:
            channels = {k: channels.get(k) or ("" if k != "addressee" else None) for k in ("speech", "action", "expression", "addressee")}
            review = None
            if injected is not None:
                review = Review("injected", {"mode": "channels", "channels": channels}, "injected", None)
                output = {**empty_output(channels), **injected, "channels": channels}
            else:
                prior = self.reviewer.get(review_id)
                if prior is not None and source in ("typed_accepted", "option") and _same(prior.channels, channels):
                    review = prior
                else:
                    calls: list[dict[str, Any]] = []
                    token = CALL_LOG.set(calls)
                    try:
                        review = await self.reviewer.review({"mode": "channels", "channels": channels}, self._encoder_context())
                    finally:
                        CALL_LOG.reset(token)
                    review.extra["llm_calls"] = calls
                if source in ("option", "option_edited") and review.output is not None:
                    pass  # options were checked when generated; the classification is what matters
                elif not review.ok:
                    self.rejections += 1
                    self.logger.event("rejected", {"source": source, **review.public()})
                    await self.push(review.message())
                    return None
                output = review.output.data if review.output else empty_output(channels)
                output = {**output, "channels": {**output.get("channels", {}), **{k: v for k, v in channels.items() if k == "addressee" and v}}}
            silent = (review is not None and review.silent) or is_empty({"mode": "channels", "channels": channels})
            record = await self._play_turn(channels, source, output, silent, review)
            self.rejections = 0
            return record

    async def request_options(self) -> list[dict[str, Any]]:
        self._require_playing()
        self.options_requests += 1
        req = self._options_request()
        res = await self.options.generate(req, self._player_guard_ctx())
        items = [{k: o.get(k) or ("" if k != "addressee" else None) for k in ("speech", "action", "expression", "addressee")} for o in res["options"]]
        self.last_options = {"turn": self.state["turn_count"], "items": res["options"], "dropped": res["dropped"]}
        self.logger.event("options", {"turn": self.state["turn_count"], **res, "request_no": self.options_requests})
        await self.push({"type": "options", "items": items or [{"speech": "", "action": "", "expression": "I wait.", "addressee": None}]})
        return res["options"]

    async def control(self, command: str, args: dict[str, Any] | None = None) -> None:
        args = args or {}
        self.logger.event("control", {"command": command, "args": args})
        if command == "start":
            await self.start(args.get("name", "Sam"), args.get("gender", "female"))
        elif command == "reset":
            self._reset_runtime()
            await self.push({"type": "session_state", "phase": "lobby", "turn": 0})
        elif command == "set_scorer":
            self.dm.set_scorer(str(args["scorer"]))
        elif command == "set_tau":
            self.dm.set_tau(float(args["tau"]))
        elif command == "force_beat":
            if args.get("beat_id") not in self.pool.by_id:
                raise SessionError("bad_beat", f"no beat {args.get('beat_id')!r}")
            self.force_beat = args["beat_id"]
        elif command == "set_state":
            patched = {**self.state, **(args.get("patch") or {})}
            errs = self.schema.validate(patched)
            if errs:
                raise SessionError("bad_state", "; ".join(errs[:3]))
            self.state = self.schema.refresh_derived(patched)
        elif command == "jump_clock":
            to = float(args["to_min"])
            events = self.clock.crossed(self.state["story_min"], to) if to > self.state["story_min"] else []
            self.state["story_min"] = to
            for ev in events:
                self.state = self._apply(self.state, ev.effects)
                if ev.phone:
                    await self._phone({**ev.phone, "id": ev.id})
            self.state = self.schema.refresh_derived(self.state)
        elif command == "inject_turn":
            await self.submit(args.get("channels") or {}, args.get("source", "filled"), injected=args.get("encoder") or {})
            return
        elif command == "set_llm_live":
            if not set_llm_live(str(args["role"]), bool(args.get("live", True))):
                raise SessionError("llm", f"role {args['role']!r} cannot go live (no provider or key)")
        elif command == "set_llm_temperature":
            client = _clients.get(str(args["role"]))
            if client is None:
                raise SessionError("llm", f"no client for role {args['role']!r}")
            client.config.temperature = float(args["temperature"])
        else:
            raise SessionError("bad_command", f"unknown command {command!r}")
        await self._push_drama_state()

    # ===================================================================== the turn
    async def _play_turn(
        self, channels: dict[str, Any], source: str, output: dict[str, Any], silent: bool, review: Review | None
    ) -> dict[str, Any]:
        calls: list[dict[str, Any]] = []
        token = CALL_LOG.set(calls)
        try:
            record = await self._turn(channels, source, output, silent, review, calls)
        finally:
            CALL_LOG.reset(token)
        return record

    async def _turn(
        self, channels: dict[str, Any], source: str, output: dict[str, Any], silent: bool, review: Review | None,
        calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        t_start = time.perf_counter()
        lat: dict[str, float] = {}
        before = deepcopy(self.state)
        turn_no = before["turn_count"] + 1
        await self.push({"type": "turn_accepted", "turn": turn_no})

        turn = build_turn(output, silent, self.turns)
        if channels.get("addressee"):
            turn["addressee"] = channels["addressee"]
        state = deepcopy(before)
        state["turn_count"] = turn_no
        state["silence_streak"] = before["silence_streak"] + 1 if silent else 0
        self.suspicion.append(float(output.get("suspicion") or 0))
        window = self.suspicion[-3:]
        state["player_suspicion"] = round(sum(window) / len(window), 2)

        # -- 1. world --------------------------------------------------------------------
        t = time.perf_counter()
        state, world = self.world.apply(state, turn["action"], turn)
        if world.status == "blocked":
            turn["blocked_by"], turn["blocked_action"] = world.blocked_by, (turn["action"] or {}).get("verb")
        notes: list[str] = []
        new_phone: list[dict[str, Any]] = []
        if before["nora_call"] == "ringing" and state["nora_call"] == "ringing":
            ev = self.clock.event("nora_call")
            state = self._apply(state, (ev.unanswered if ev else None) or {"nora_call": "missed"})
            notes.append("My phone stops ringing.")
            new_phone.append({"kind": "missed_call", "from": "nora", "id": f"nora_missed_{turn_no}"})
        if world.status == "done" and (turn["action"] or {}).get("verb") == "listen_voicemail":
            new_phone.append({"kind": "voicemail", "from": "leo", "text": world.note, "id": "leo_voicemail"})
        state, world = self.world.settle(state, world)

        run = self.run
        refused = False
        if run is not None and run.invite_pending:
            invite = run.entry["invite"]
            if accepts_invite(invite, turn):
                run.invite_pending = False
                state = self._apply(state, {"player_room": invite["to_room"], f"{invite['asker']}_room": invite["to_room"]})
            else:
                refused = True
                state = self._apply(state, {f"{invite['asker']}_room": invite["to_room"]})
                notes.append(f"{invite['asker'].capitalize()} shrugs and goes to the {invite['to_room']} alone.")
        lat["world"] = _ms(t)

        # -- 2. reactions, the answer, the caps -----------------------------------------------
        t = time.perf_counter()
        heard = state.get("heard_by") or {}
        turn["fresh"] = {h: [f for f in turn["claims"] if h not in heard.get(f, [])] for h in ("julian", "mia")}
        reaction = self.reactions.select(state, turn, None if refused else run, self.used, self.last_speaker)
        for r in reaction.chosen():
            if r.once:
                self.used.add(r.id)
        for e in reaction.effects:
            state = self._apply(state, e["effects"])
        outcome = None
        if run is not None and run.awaiting and not refused:
            outcome = run.choose_outcome(rule_ctx(state, turn))
            run.answer(outcome)
            if outcome and outcome.get("effects"):
                state = self._apply(state, outcome["effects"])
        state, clipped = self.reactions.cap_deltas(before, state)
        state = self.reactions.recover(before, state)
        state = self.reactions.record_claims(state, turn, turn_no)
        state = self.schema.refresh_derived(state)
        lat["reactions"] = _ms(t)

        # -- 3. steps --------------------------------------------------------------------------
        plan: list[dict[str, Any]] = []
        resume = False
        if run is not None and not refused:
            run.turns += 1
            plan = run.plan(interrupted=bool(reaction.primary and reaction.primary.type in INTERRUPT_TYPES))
            resume = bool(plan) and run.interrupted
            run.interrupted = not plan and bool(run.remaining) and not run.awaiting and not run.invite_pending
            run.deliver(plan)

        # -- 4. does the beat end? ----------------------------------------------------------------
        ended: dict[str, Any] | None = None
        events: list[ClockEvent] = []
        if run is not None:
            status, by = None, None
            if refused:
                status, by = "aborted", "refused"
            elif run.finished:
                status = "completed"
            else:
                must = self.pool.must_follow(state, turn, exclude=run.beat.id)
                if must is not None:
                    status, by = "aborted", must.id
                elif self.pool.should_abort(run.beat, rule_ctx(state, turn)):
                    status, by = "aborted", "abort_if"
            if status:
                state, events, ended = self._end_beat(state, run, status, by)
                self.run = None
        hold = any(e.hold_beat_choice for e in events)
        for e in events:
            notes += self._event_lines(e)
            if e.phone:
                new_phone.append({**e.phone, "id": e.id})

        # -- 5. the next beat ------------------------------------------------------------------------
        decision: Decision | None = None
        opening: dict[str, Any] | None = None
        ending: dict[str, Any] | None = None
        fast_forward = False
        generated: dict[str, Any] | None = None
        t = time.perf_counter()
        if self.run is None and not hold and state.get("ending") is None:
            while True:
                decision = await self._decide(state, turn)
                if decision.kind == "empty":
                    ev = self.clock.next_pending(state["story_min"]) if self.clock.fast_forward_gaps else None
                    if ev is not None:
                        state = self._apply({**state, "story_min": ev.at_min}, ev.effects)
                        state = self.schema.refresh_derived(state)
                        fast_forward = True
                        notes += self._event_lines(ev)
                        if ev.phone:
                            new_phone.append({**ev.phone, "id": ev.id})
                        if ev.hold_beat_choice:
                            break
                        continue
                    decision, generated = await self._generate(state, turn, decision)
                elif decision.kind == "generate":
                    decision, generated = await self._generate(state, turn, decision)
                break
            if decision is not None and decision.chosen_beat is not None:
                if decision.chosen_beat.is_ending:
                    state, ending = self._play_ending(state, decision)
                else:
                    opening = self._start_beat(decision, turn_no)
                    state["consecutive_generated"] = state["consecutive_generated"] + 1 if decision.chosen_beat.origin == "generated" else 0
        lat["dm"] = _ms(t)
        self._sync_run(state)
        self.state = state

        # -- 6. narration and guard -------------------------------------------------------------------
        t = time.perf_counter()
        reactions_req = [{"role": "primary" if r is reaction.primary else "secondary", "responder": r.responder, "do": r.do} for r in reaction.chosen()]
        world_req = world.public() if world.status in ("done", "failed", "blocked", "held") or world.follow_notes or world.before else None
        req = self._request(
            state, turn_no, player=channels, world=world_req, reactions=reactions_req,
            outcome={"id": outcome["id"], "text": outcome["text"]} if outcome else None,
            steps=run.beat.resolve(plan, rule_ctx(state, turn)) if run is not None and plan else plan,
            resume=resume, events=notes, fast_forward=fast_forward, opening=opening, ending=ending,
            moves=story_ledger.moves(before, state),
        )
        extra_allowed = set(world.reveals)
        for e in reaction.effects + ([{"effects": outcome.get("effects")}] if outcome else []):
            rev = (e.get("effects") or {}).get("revealed")
            if isinstance(rev, list) and rev[:1] == ["add"]:
                extra_allowed |= set(rev[1:])
        beat_for_guard = ended["beat"] if ended else (run.beat if run else None)
        if beat_for_guard is not None:
            extra_allowed |= beat_for_guard.reveals()
        out, guard_log = await self._narrate(req, state, channels, extra_allowed, [s["id"] for s in plan], ending=ending is not None, world=world)
        lat["narrator_guard"] = _ms(t)

        # -- 7. emit, log --------------------------------------------------------------------------------
        final = self.state.get("ending") is not None
        tableau = pick_tableau(plan + (ending["steps"] if ending else []), ending["beat"] if ending else None)
        await self._emit_passage(turn_no, channels, out["segments"], tableau, final)
        for ev in new_phone:
            await self._phone(ev)
        self.turns.append(turn)
        if ended is not None or ending is not None:
            self._measure_tension()
        lat["total"] = _ms(t_start)
        review_calls = (review.extra.get("llm_calls") if review else None) or []
        lat["review_before_submit"] = round(sum(c["latency_ms"] for c in review_calls), 1)
        record = {
            "turn": turn_no,
            "session": self.id,
            "input": {
                "channels": channels, "source": source, "review_id": review.id if review else None,
                "review": review.public() if review else None, "rejections_before": self.rejections,
            },
            "understanding": output,
            "turn_ns": turn,
            "world": world.public(),
            "reactions": {**reaction.public(), "effects": reaction.effects, "clipped": clipped},
            "beat": {
                "run": run.public() if run else None, "planned": [s["id"] for s in plan], "outcome": outcome["id"] if outcome else None,
                "ended": {k: v for k, v in ended.items() if k != "beat"} if ended else None, "resume": resume,
            },
            "clock": {"story_min": state["story_min"], "before": before["story_min"], "events": [e.id for e in events], "fast_forward": fast_forward, "hold": hold},
            "decision": decision.public() if decision else None,
            "generated": generated,
            "narrator": out,
            "guard": guard_log,
            "options": self.last_options if self.last_options and self.last_options["turn"] == before["turn_count"] else None,
            "state_diff": self.schema.diff(before, state),
            "state": deepcopy(state),
            "latency_ms": lat,
            "llm_calls": review_calls + calls,
            "model_versions": self._model_versions(),
        }
        await self._finish_turn(record)
        if final:
            await self._end_session()
        return record

    # ===================================================================== beats
    async def _decide(self, state: dict[str, Any], turn: dict[str, Any]) -> Decision:
        if self._tension_task is not None:
            await self._tension_task
            self._tension_task = None
        force, self.force_beat = self.force_beat, None
        decision = await self.dm.decide(
            state, turn, decision_idx=self.decision_idx, state_text=self.schema.textualize(state), tension=self.tension_measured,
            recent_dialogue=self._recent_lines(), last_input=self.passages[-1]["player"] if self.passages else None,
            exclude=self.run.beat.id if self.run else None, force_beat_id=force,
        )
        self.decision_idx += 1
        self.last_decision = decision
        if decision.kind != "empty":
            self.logger.decision({"session": self.id, "turn": state.get("turn_count", 0), "story_min": state.get("story_min"),
                                  "state_text": self.schema.textualize(state), **decision.public()})
        return decision

    async def _generate(self, state: dict[str, Any], turn: dict[str, Any], decision: Decision) -> tuple[Decision, dict[str, Any]]:
        res = await self.proposer.generate(
            pool=self.pool, state=state, turn=turn, state_text=self.schema.textualize(state),
            recent_dialogue=self._recent_lines(), last_input=self.passages[-1]["player"] if self.passages else None,
        )
        info = res.public()
        self.logger.event("generated", {"turn": state.get("turn_count"), **info})
        if res.accepted:
            for b in res.accepted:
                self.pool.add(b)
            chosen, scores = await self.dm.rank(
                state, turn, res.accepted, decision_idx=self.decision_idx, state_text=self.schema.textualize(state),
                tension=self.tension_measured, recent_dialogue=self._recent_lines(),
            )
            info["chosen"], info["scores"] = chosen.id, scores
            entry = self.pool.entry_for(chosen, rule_ctx(state, turn)) or chosen.entries[0]
            return Decision(decision.decision_idx, "generate", chosen, entry, decision.candidates, decision.scorer_used,
                            decision.tau, decision.tier, decision.reasoning + f"; generated {chosen.id}"), info
        fallback = self.dm.best_authored(decision)
        info["fallback"] = fallback.id if fallback else None
        if fallback is None:
            return Decision(decision.decision_idx, "empty", reasoning="generation failed and nothing to fall back on"), info
        entry = self.pool.entry_for(fallback, rule_ctx(state, turn))
        return Decision(decision.decision_idx, "scored", fallback, entry, decision.candidates, decision.scorer_used, decision.tau,
                        decision.tier, decision.reasoning + "; generation failed, best shelf beat"), info

    def _start_beat(self, decision: Decision, turn_no: int) -> dict[str, Any] | None:
        beat = decision.chosen_beat
        if beat is None:
            return None
        entry = decision.entry or beat.entries[0]
        self.run = BeatRun.start(beat, entry, turn_no)
        self._sync_run(self.state)
        return {"beat": beat.id, "entry": entry["id"], "text": entry["opening"], "invite": entry.get("invite")}

    def _end_beat(self, state: dict[str, Any], run: BeatRun, status: str, by: str | None):
        beat = run.beat
        done = status == "completed"
        if done:
            state = self._apply(state, beat.effects)
            present = WorldRules.present(state)
            state["heard_by"] = {**state.get("heard_by", {}), beat.id: present}
        before = float(state["story_min"])
        minutes = self.clock.minutes_for(beat.minutes, before)
        state["story_min"] = round(before + minutes, 2)
        state["beat_history"] = [*state["beat_history"], {
            "beat_id": beat.id, "origin": beat.origin, "completed": done, "aborted_by": by, "entry": run.entry.get("id"),
            "outcome": run.outcome, "turns": run.turns, "story_min_end": state["story_min"],
        }]
        events = self.clock.crossed(before, state["story_min"])
        for e in events:
            state = self._apply(state, e.effects)
        state = self.schema.refresh_derived(state)
        return state, events, {"beat": beat, "beat_id": beat.id, "status": status, "by": by, "minutes": minutes}

    def _play_ending(self, state: dict[str, Any], decision: Decision) -> tuple[dict[str, Any], dict[str, Any]]:
        """An ending plays out whole in the passage that reaches it: opening, every step, the epilogue."""
        beat = decision.chosen_beat
        entry = decision.entry or beat.entries[0]
        steps = beat.resolve(beat.steps, rule_ctx(state, {}))  # before its effects: "unless the crate is already open"
        state = self._apply(state, beat.effects)
        state["beat_history"] = [*state["beat_history"], {
            "beat_id": beat.id, "origin": beat.origin, "completed": True, "aborted_by": None, "entry": entry.get("id"),
            "outcome": None, "turns": 0, "story_min_end": state["story_min"],
        }]
        state = self.schema.refresh_derived(state)
        self.run = None
        return state, {"beat": beat, "beat_id": beat.id, "opening": entry["opening"], "steps": steps, "epilogue": beat.epilogue}

    def _sync_run(self, state: dict[str, Any]) -> None:
        run = self.run
        state["current_beat"] = run.beat.id if run else None
        state["beat_step"] = run.step if run else 0
        state["beat_turns"] = run.turns if run else 0

    @staticmethod
    def _event_lines(ev: ClockEvent) -> list[str]:
        phone = ev.phone or {}
        if phone.get("kind") == "text":
            return [f"My phone buzzes. Nora: '{phone.get('text', '')}'"]
        if phone.get("kind") == "call_incoming":
            return ["My phone starts to ring. Nora."]
        return []

    # ===================================================================== narration
    def _request(self, state: dict[str, Any], turn_no: int, **kw: Any) -> NarrationRequest:
        present = self.world.present(state)
        speakers = list(present)
        if state.get("nora_call") == "answered" and self.run and self.run.beat.id == "noras_call" and "nora" not in speakers:
            speakers.append("nora")
        ending = kw.pop("ending", None)
        opening = kw.pop("opening", None)
        if ending:
            opening = {"text": ending["opening"]}
            ending = {"steps": ending["steps"], "epilogue": ending.get("epilogue")}
        return NarrationRequest(
            name=self.name, gender=self.gender, turn=turn_no, room=state["player_room"], present=present,
            knowledge=self.knowledge.slice(state, speakers, self.world.perceivable(state)),
            words=self.clock.passage_words(state["story_min"]), recent=[p["text"] for p in self.passages[-2:]],
            positions=story_ledger.positions(state), ledger=story_ledger.history(state), said=story_ledger.said(self.passages),
            opening=opening, ending=ending, **kw,
        )

    async def _narrate(
        self, req: NarrationRequest, state: dict[str, Any], player: dict[str, Any] | None, extra_allowed, planned: list[str],
        ending: bool = False, world: WorldResult | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        gctx = GuardContext(
            allowed=set(state.get("revealed", [])) | set(extra_allowed),
            speaker_allowed={n: self.knowledge.allowed_facts(n, state) for n in NPCS},
            player={**(player or {}), "world_note": bool(world and (world.note or world.follow_notes))},
            ending=ending, knowledge=req.knowledge,
            scene={
                "room": state["player_room"], "present": self.world.present(state),
                **{f"{n}_room": state[f"{n}_room"] for n in NPCS},
                **{k: state[k] for k in ("crate", "leo_phone", "player_phone", "nora_call")},
                "heard_by": state.get("heard_by", {}),
                "moves": req.moves,
            },
        )
        deadline = time.monotonic() + float(os.getenv("NARRATOR_TURN_BUDGET_S") or NARRATION_BUDGET_S)
        out = await self.narrator.write(req, deadline)
        log: list[dict[str, Any]] = []
        rewrites = 0
        while True:
            verdict = await self.guard.check(out.segments, gctx)
            fails = Guard.failures(verdict.result["verdicts"])
            steps_ok = sorted(out.steps_delivered) == sorted(planned)
            log.append({"attempt": rewrites, "verdicts": verdict.log(), "steps_delivered": out.steps_delivered, "steps_ok": steps_ok})
            if (not fails and steps_ok) or rewrites >= MAX_GUARD_REWRITES or time.monotonic() >= deadline:
                break
            if not fails and rewrites >= 1:
                break  # a steps mismatch gets one rewrite, then the engine moves on and logs it
            hints = [f"segment {f['index']}: {f['label']}" + (f" ({f['fact']})" if f.get("fact") else "") + (f": {f['span']!r}" if f.get("span") else "") for f in fails]
            if not steps_ok:
                hints.append(f"deliver exactly these steps and report them in steps_delivered: {planned}")
            req.hints = hints
            redo = await self.narrator.write(req, deadline)
            rewrites += 1
            if redo.fallback and not out.fallback:
                # no model could rewrite in time: keep the written draft and repair it rather than show stitched text
                log.append({"attempt": rewrites, "kept_previous": True, "errors": redo.meta.get("errors")})
                break
            out = redo
        segments = out.segments
        repaired = False
        if fails:
            segments = repair(segments, fails, player)
            repaired = True
        req.hints = []
        return {**out.public(), "segments": segments, "rewrites": rewrites, "repaired": repaired}, log

    async def _emit_passage(self, turn_no: int, player: dict[str, Any] | None, segments: list[dict[str, Any]], tableau: str | None, final: bool) -> None:
        segments = [{**s, "text": fill(s["text"], self.name)} for s in segments]
        for s in reversed(segments):
            if s["kind"] == "speech" and s.get("speaker"):
                self.last_speaker = s["speaker"]
                break
        text = " ".join(s["text"] for s in segments)
        self.passages.append({"turn": turn_no, "player": player, "segments": segments, "text": text})
        msg: dict[str, Any] = {"type": "passage", "turn": turn_no, "player": player, "segments": segments, "tableau": tableau, "final": final,
                               "illustration": self._illustration(tableau)}
        await self.push(msg)
        await self.push({"type": "room_state", "player_room": self.state["player_room"], "present": self.world.present(self.state)})

    def _illustration(self, tableau: str | None) -> dict[str, Any] | None:
        """The caption (and the image for the player's gender, when there is one) of a moment not shown yet."""
        entry = self.tableaux.get(tableau or "")
        if entry is None or tableau in self.shown_tableaux:
            return None
        self.shown_tableaux.add(tableau)
        out = {"id": tableau, "caption": entry["caption"]}
        src = (entry.get("images") or {}).get(self.gender)
        if src:
            out["src"] = src
        return out

    # ===================================================================== bookkeeping
    async def _finish_turn(self, record: dict[str, Any]) -> None:
        self.traces.append(record)
        self.logger.turn(record)
        await self.push({"type": "turn_trace", "turn": record["turn"], "record": record})
        await self._push_drama_state()

    async def _end_session(self) -> None:
        if self._tension_task is not None:
            await self._tension_task
        self.phase = "ended"
        summary = {
            "session": self.id,
            "ending": self.state.get("ending"),
            "turns": self.state["turn_count"],
            "story_min": self.state["story_min"],
            "beats": [h["beat_id"] for h in self.state["beat_history"]],
            "aborted": [h["beat_id"] for h in self.state["beat_history"] if not h["completed"]],
            "tension_trace": self.tension_trace,
            "arc_distance": self.dm.arc.distance([(p["story_min"], p["tension"]) for p in self.tension_trace]),
            "model_versions": self._model_versions(),
        }
        self.logger.finish(summary)
        await self.push({"type": "session_state", "phase": "ended", "turn": self.state["turn_count"]})

    def _measure_tension(self) -> None:
        window = [p["text"] for p in self.passages[-TENSION_WINDOW:]]
        state = deepcopy(self.state)

        async def run() -> None:
            res = await self.tension.estimate(window, state)
            self.tension_measured = float(res.result["tension"])
            self.tension_trace.append({"turn": state["turn_count"], "story_min": state["story_min"], "tension": self.tension_measured,
                                       "declared": state["tension"], "estimate": res.log()})

        self._tension_task = asyncio.ensure_future(run())

    async def _phone(self, ev: dict[str, Any]) -> None:
        self.phone.append(ev)
        await self.push({"type": "phone_event", **{k: v for k, v in ev.items() if k in ("kind", "from", "text", "id") and v is not None}})

    async def _push_drama_state(self) -> None:
        await self.push({"type": "drama_state", **self.drama_state()})

    def drama_state(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "state": self.state,
            "state_text": self.schema.textualize(self.state),
            "run": self.run.public() if self.run else None,
            "shelf": self.pool.shelf(self.state, self.turns[-1] if self.turns else {}),
            "last_decision": self.last_decision.public() if self.last_decision else None,
            "tension_measured": self.tension_measured,
            "tension_trace": self.tension_trace,
            "target_now": self.dm.arc.target_at(self.state["story_min"]),
            "arc": self.dm.arc.points,
            "used_reactions": sorted(self.used),
            "scorer": self.dm.scorer,
            "tau": self.dm.tau,
            "models": self._model_versions(),
        }

    def _model_versions(self) -> dict[str, Any]:
        return {
            "encoder": self.encoder.active, "guard": self.guard.active, "tension": self.tension.active, "scorer": self.dm.scorer,
            "shadow": self.encoder.shadow,
            "llm": {r: {"provider": c.config.effective_provider, "model": c.config.model if c.config.effective_provider != "mock" else "mock"} for r, c in _clients.items()},
        }

    def _encoder_context(self) -> dict[str, Any]:
        s = self.state
        run = self.run
        asking = run.asking_step() if run else None
        return {
            "player_room": s["player_room"],
            "present": self.world.present(s),
            "on_call_with_nora": s["nora_call"] == "answered" and bool(run and run.beat.id == "noras_call"),
            "phone_ringing": s["nora_call"] == "ringing",
            "story_phase": s["story_phase"],
            "asking": asking.get("asks") if asking else None,
            "recent_npc_lines": self._recent_lines(2),
        }

    def _options_request(self) -> dict[str, Any]:
        s = self.state
        run = self.run
        asking = run.asking_step() if run else None
        return {
            "name": self.name, "room": s["player_room"], "present": self.world.present(s),
            "asking": asking.get("asks") if asking else None,
            "invite": run.entry.get("invite") if run and run.invite_pending else None,
            "ringing": s["nora_call"] == "ringing", "side": s["side"], "revealed": s["revealed"],
            "player_phone": s["player_phone"], "can_see": self.world.perceivable(s),
            "composure": {"julian": s["julian_composure"], "mia": s["mia_composure"]},
            "last_speaker": self.last_speaker, "last_passage": self.passages[-1]["text"] if self.passages else "",
            "player_knows": self.knowledge.slice(s, [], self.world.perceivable(s))["player"],
        }

    def _player_guard_ctx(self) -> GuardContext:
        return GuardContext(allowed=set(self.state.get("revealed", [])), player={})

    def _recent_lines(self, n: int = 6) -> list[str]:
        lines = []
        for p in self.passages[-3:]:
            for s in p["segments"]:
                if s["kind"] == "speech":
                    lines.append(f"{(s.get('speaker') or '?').capitalize()}: {s['text']}")
                elif s["kind"] == "me_speech":
                    lines.append(f"You: {s['text']}")
        return lines[-n:]

    def _apply(self, state: dict[str, Any], effects: dict[str, Any] | None) -> dict[str, Any]:
        return apply_effects(state, effects or {}, self.schema.props)

    def _require_playing(self) -> None:
        if self.phase != "playing":
            raise SessionError("not_playing", f"session is {self.phase}")


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all((a.get(k) or "") == (b.get(k) or "") for k in ("speech", "action", "expression")) and (
        not b.get("addressee") or a.get("addressee") == b.get("addressee")
    )


def _ms(t: float) -> float:
    return round((time.perf_counter() - t) * 1000, 1)


__all__ = ["Session", "SessionError"]
