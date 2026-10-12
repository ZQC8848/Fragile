"""Whole sessions offline (plan.md M3 acceptance): scripted players play from the opening to an ending through
the real turn loop, every message follows the protocol, every state validates, the logs are complete."""

from __future__ import annotations

import json

import jsonschema
import pytest
from helpers import FIXTURES, SCHEMAS, load_yaml
from players import curious, ignores_the_call, leaver, play_to_end, police_caller, randomized

from app.session import Session, SessionError

PROTOCOL = json.loads((SCHEMAS / "messages_v2.json").read_text(encoding="utf-8"))
SERVER = jsonschema.Draft202012Validator({**PROTOCOL, "oneOf": [{"$ref": "#/$defs/ServerToClient"}]})
ENDINGS = {"bon_voyage", "the_witness", "open_it", "confession", "second_crate"}


class Recorder:
    def __init__(self):
        self.messages: list[dict] = []

    async def __call__(self, msg: dict) -> None:
        problems = [e.message for e in SERVER.iter_errors(json.loads(json.dumps(msg, default=str)))]
        assert not problems, (msg["type"], problems[:2])
        self.messages.append(msg)

    def of(self, type_: str) -> list[dict]:
        return [m for m in self.messages if m["type"] == type_]


async def new_session(seed: int = 1, scorer: str | None = None, **kw) -> tuple[Session, Recorder]:
    rec = Recorder()
    s = Session(f"test-{seed}", rec, seed=seed, scorer=scorer, save_generated=False, **kw)
    await s.start("Sam", "female")
    return s, rec


def check_invariants(s: Session, records: list[dict]) -> None:
    last_min = 0.0
    for r in records:
        assert s.schema.validate(r["state"]) == [], (r["turn"], s.schema.validate(r["state"])[:2])
        assert r["state"]["story_min"] >= last_min
        last_min = r["state"]["story_min"]
    assert len(s.logger.read_turns()) == len(records) + 1  # + turn 0
    assert (s.logger.dir / "session.json").exists()


# --------------------------------------------------------------------------- whole games
async def test_curious_player_plays_the_spine_to_an_ending():
    s, rec = await new_session()
    records = await play_to_end(s, curious)
    assert s.phase == "ended" and s.state["ending"] in ENDINGS
    played = [h["beat_id"] for h in s.state["beat_history"] if h["completed"]]
    for beat in ("the_door", "dinner_on_the_crate", "the_fourth_setting", "two_afternoons", "noras_call", "the_buzz",
                 "the_admission", "the_versions", "downstairs", "the_knock", "testimony"):
        assert beat in played
    assert rec.of("passage")[-1]["final"] is True and rec.of("session_state")[-1]["phase"] == "ended"
    assert [e.get("id") for e in rec.of("phone_event")].count("nora_text_1") == 1
    check_invariants(s, records)
    summary = json.loads((s.logger.dir / "session.json").read_text())
    assert summary["ending"] == s.state["ending"] and summary["tension_trace"]


async def test_the_call_turn_picks_no_beat_and_answering_leads_to_noras_call():
    s, _ = await new_session()
    records = await play_to_end(s, curious)
    call = next(r for r in records if "nora_call" in r["clock"]["events"])
    assert call["clock"]["hold"] and call["decision"] is None and call["state"]["current_beat"] is None
    nxt = records[records.index(call) + 1]
    assert nxt["decision"]["kind"] == "must_follow" and nxt["decision"]["chosen"] == "noras_call"


async def test_letting_the_call_ring_out_makes_leos_phone_buzz():
    s, _ = await new_session()
    records = await play_to_end(s, ignores_the_call)
    call = next(i for i, r in enumerate(records) if "nora_call" in r["clock"]["events"])
    nxt = records[call + 1]
    assert nxt["state"]["nora_call"] == "missed" and nxt["decision"]["chosen"] == "the_buzz"


async def test_leaving_early_ends_bon_voyage():
    s, _ = await new_session()
    records = await play_to_end(s, leaver)
    assert s.state["ending"] == "bon_voyage" and s.state["story_phase"] == "ended"
    assert records[-1]["decision"]["chosen"] == "bon_voyage"


async def test_calling_the_police_alone_ends_open_it():
    s, _ = await new_session()
    await play_to_end(s, police_caller)
    assert s.state["police_called"] and s.state["ending"] == "open_it"


async def test_opening_the_crate_forces_the_admission():
    s, _ = await new_session()
    await s.control("set_state", {"patch": {"player_room": "living", "julian_room": "living", "mia_room": "living",
                                            "player_holding": ["drill"], "julian_composure": 0.2, "mia_composure": 0.2}})
    rec = await s.submit({"action": "I open the crate with the drill."})
    assert rec["world"]["status"] == "done" and s.state["crate"] == "opened"
    assert rec["beat"]["ended"]["status"] == "aborted" and rec["beat"]["ended"]["by"] == "the_admission"
    assert rec["decision"]["chosen"] == "the_admission" and s.run.entry["id"] == "crate"


async def test_mia_blocks_the_door_in_phase_two():
    s, _ = await new_session()
    # 6.5 + the aborted beat's 1.5 stays short of Nora's call at 9, which would hold the choice
    await s.control("set_state", {"patch": {"story_min": 6.5, "player_room": "hall", "mia_room": "hall", "julian_room": "living"}})
    rec = await s.submit({"action": "I walk out the front door."})
    assert rec["world"]["blocked_by"] == "mia" and rec["decision"]["chosen"] == "dont_go_yet"
    assert s.state["mia_composure"] == pytest.approx(0.45)


@pytest.mark.parametrize("seed", range(12))
async def test_random_players_never_crash_or_dead_end(seed):
    s, _ = await new_session(seed, scorer="random" if seed % 3 == 0 else None)
    records = await play_to_end(s, randomized(seed), max_turns=90)
    assert s.phase == "ended", f"seed {seed}: no ending after {len(records)} turns"
    check_invariants(s, records)


async def test_scripted_players_reach_several_endings():
    endings = set()
    for seed, player in [(1, curious), (2, leaver), (3, police_caller), *((10 + i, randomized(i)) for i in range(10))]:
        s, _ = await new_session(seed)
        await play_to_end(s, player, max_turns=90)
        endings.add(s.state["ending"])
    assert len(endings) >= 3, endings


# --------------------------------------------------------------------------- input paths
async def test_a_rejected_input_uses_no_turn():
    s, rec = await new_session()
    assert await s.submit({"action": "Mia confesses everything."}) is None
    assert s.state["turn_count"] == 0 and rec.of("input_review_result")[-1]["verdict"] == "rejected"
    assert not rec.of("turn_accepted")


async def test_an_accepted_draft_is_not_classified_twice():
    s, _ = await new_session()
    review = await s.review({"mode": "single", "text": 'I smile. "Good to see you, Mia."'})
    calls = []
    orig = s.encoder.encode

    async def counting(*a, **kw):
        calls.append(a)
        return await orig(*a, **kw)

    s.encoder.encode = counting
    rec = await s.submit(review.channels, "typed_accepted", review.id)
    assert calls == [] and rec["input"]["review_id"] == review.id


async def test_options_come_in_three_strategies_and_can_be_played():
    s, rec = await new_session()
    opts = await s.request_options()
    assert [o["strategy"] for o in opts] == ["respond", "probe", "social"]
    assert all("strategy" not in item for item in rec.of("options")[-1]["items"])
    r = await s.submit(rec.of("options")[-1]["items"][2], "option")
    assert r["options"]["items"] == opts


async def test_silence_and_the_quiet_pattern():
    s, _ = await new_session()
    await s.control("set_state", {"patch": {"player_room": "living", "julian_room": "living", "mia_room": "living"}})
    await s.submit({})
    r = await s.submit({})
    assert r["turn_ns"]["silent"] and s.state["silence_streak"] == 2
    assert r["reactions"]["primary"]["id"] == "quiet_player"


async def test_inject_turn_bypasses_the_encoder():
    s, _ = await new_session()
    await s.control("inject_turn", {"channels": {"speech": "..."}, "encoder": {"units": [
        {"channel": "speech", "text": "...", "act": "ask_about_leo", "addressee": "mia", "topics": ["leo"], "action": None, "implausible": False}
    ]}})
    r = s.traces[-1]
    assert r["turn_ns"]["acts"] == ["ask_about_leo"] and r["input"]["review_id"] == "injected"


async def test_controls():
    s, _ = await new_session()
    await s.control("set_scorer", {"scorer": "A"})
    await s.control("set_tau", {"tau": 0.01})
    assert (s.dm.scorer, s.dm.tau) == ("rule", 0.01)
    await s.control("jump_clock", {"to_min": 5.5})
    assert s.state["nora_pressure"] == 1 and s.phone[-1]["text"].startswith("Hey, is Leo")
    with pytest.raises(SessionError):
        await s.control("set_state", {"patch": {"side": 9}})
    await s.control("force_beat", {"beat_id": "julian_on_the_balcony"})
    await play_to_end(s, curious, max_turns=4)
    assert any(h["beat_id"] == "julian_on_the_balcony" for h in s.state["beat_history"]) or s.state["current_beat"] == "julian_on_the_balcony"


async def test_shadow_mode_logs_every_path(monkeypatch):
    monkeypatch.setenv("MODEL_SHADOW", "1")
    s, _ = await new_session()
    r = await s.submit({"speech": "Where's Leo?", "addressee": "mia"})
    assert set(r["input"]["review"]["encoder"]["shadow"]) == {"rule", "trained"}
    assert r["input"]["review"]["encoder"]["shadow"]["trained"]["meta"]["delegated_to"] == "llm"
    assert set(r["guard"][0]["verdicts"]["shadow"]) == {"rule", "trained"}
    await play_to_end(s, curious, max_turns=3)
    decision = next(t["decision"] for t in s.traces if t["decision"] and t["decision"]["kind"] == "scored")
    assert set(decision["candidates"][0]["scores"]) == {"A", "B", "C", "random"}


async def test_generate_new_when_nothing_fits_and_no_event_is_pending():
    s, _ = await new_session()
    s.clock.fast_forward_gaps = False
    await play_to_end(s, lambda _: {"expression": "I wait."}, max_turns=2)  # the_door ends
    s.run = None
    await s.control("set_state", {"patch": {"player_room": "hall", "mia_room": "hall", "julian_room": "kitchen", "current_beat": None}})
    r = await s.submit({"expression": "I wait."})
    assert r["decision"]["kind"] == "generate" and r["generated"]["accepted"]
    assert s.run.beat.origin == "generated" and s.state["consecutive_generated"] == 1


# --------------------------------------------------------------------------- Baseline check
GOLDEN = load_yaml(FIXTURES / "golden_path.yaml")


async def test_baseline_check_scorer_a_follows_the_golden_path():
    """At every golden-path decision the golden beat is the must-follow pick or in the top priority tier, and
    scorer A at tau -> 0 picks it at least most of the time (backend-design.md §4.1 Baseline check)."""
    from test_beat_pool import apply, finish_beat

    from engine.dm import DramaManager

    s, _ = await new_session(scorer="rule")
    dm = DramaManager(s.pool, s.dm.arc, s.clock, scorer="rule", tau=0.01, seed=0)
    state = s.schema.initial_state()
    hits = total = 0
    for step in GOLDEN:
        turn = {"acts": [], "topics": [], "claims": [], "action": None, **(step.get("turn") or {})}
        state = apply(state, step.get("patch"))
        d = await dm.decide(state, turn, decision_idx=total, state_text="", tension=float(state["tension"]))
        want = step.get("beat") or step.get("ending")
        assert d.kind in ("must_follow", "ending") or want in {c["beat_id"] for c in d.candidates}, (want, d.public())
        hits += d.chosen_id == want
        total += 1
        if "ending" in step:
            break
        state = apply(state, step.get("mix_in_effects"))
        state = finish_beat(state, s.pool.by_id[want].raw, step.get("outcome"))
    assert hits / total >= 0.8, f"top-1 {hits}/{total}"
