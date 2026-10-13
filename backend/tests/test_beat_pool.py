"""M2 content tests: the beat pool v0 and the reaction table validate, every rule compiles against
state_v2, the golden path replays (Baseline check), and every ending is reachable.

The replay below is a deliberately small stand-in for the drama manager (eligibility, must-follow
ranks, effects, clock events). It checks the CONTENT; the engine gets its own tests in M3."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

import pytest
from helpers import (
    DATA,
    FIXTURES,
    SCHEMAS,
    STATE,
    STATE_PROPS,
    check_effects,
    check_rule,
    default_state,
    errors,
    load_json,
    load_yaml,
)

from engine.beats import BeatPool, rule_ctx
from engine.dsl import apply_effects, compile_expr, truthy

BEAT_SCHEMA = load_json(SCHEMAS / "beat_v2.json")
BEATS: list[dict[str, Any]] = [b for p in sorted((DATA / "beats").glob("*.yaml")) for b in load_yaml(p)]
BY_ID = {b["id"]: b for b in BEATS}
REACTIONS = load_yaml(DATA / "reactions.yaml")
CLOCK = load_yaml(DATA / "clock.yaml")

EXPECTED_MUST_FOLLOW = {
    "bon_voyage": 1, "second_crate": 2, "open_it": 3, "the_admission": 4, "noras_call": 5,
    "the_buzz": 6, "dont_go_yet": 7, "downstairs": 8, "the_knock": 9, "testimony": 10,
}
EXPECTED_ENDING_RANK = {"confession": 1, "open_it": 2, "the_witness": 3, "bon_voyage": 4, "second_crate": 5}


# --------------------------------------------------------------------------- pool shape
def test_pool_is_the_twenty_beats_of_beat_script():
    ids = [b["id"] for b in BEATS]
    assert len(ids) == len(set(ids)) == 20
    types = [b["type"] for b in BEATS]
    assert (types.count("spine"), types.count("satellite"), types.count("ending")) == (14, 1, 5)


@pytest.mark.parametrize("beat", BEATS, ids=lambda b: b["id"])
def test_beat_validates(beat: dict[str, Any]):
    assert errors(BEAT_SCHEMA, beat) == []


def _rules(beat: dict[str, Any]) -> list[str]:
    rules = [beat["preconditions"], beat.get("abort_if"), (beat.get("must_follow") or {}).get("when")]
    rules += [e.get("when") for e in beat["entries"]]
    rules += [m["when"] for m in beat.get("mix_in", [])]
    rules += [o.get("when") for o in beat.get("outcomes", [])]
    rules += [p["when"] for p in beat.get("priority_test", [])]
    return [r for r in rules if r]


@pytest.mark.parametrize("beat", BEATS, ids=lambda b: b["id"])
def test_beat_rules_compile_and_effects_are_valid(beat: dict[str, Any]):
    for r in _rules(beat):
        check_rule(r, beat["id"])
    for eff in [beat["effects"], *(o.get("effects") for o in beat.get("outcomes", [])), *(m.get("effects") for m in beat.get("mix_in", []))]:
        check_effects(eff, beat["id"])


@pytest.mark.parametrize("beat", BEATS, ids=lambda b: b["id"])
def test_played_refers_to_existing_beats(beat: dict[str, Any]):
    import re

    for r in _rules(beat):
        for ref in re.findall(r"played\('([a-z_]+)'\)", r):
            assert ref in BY_ID, f"{beat['id']}: played({ref!r}) refers to no beat"


@pytest.mark.parametrize("beat", [b for b in BEATS if any("asks" in s for s in b["steps"])], ids=lambda b: b["id"])
def test_asking_steps_have_matching_outcomes(beat: dict[str, Any]):
    outcome_ids = [o["id"] for o in beat.get("outcomes", [])]
    for step in beat["steps"]:
        asks = step.get("asks")
        if not asks:
            continue
        assert outcome_ids, f"{beat['id']}: asking step without outcomes"
        if asks.get("on_silence"):
            assert asks["on_silence"] in outcome_ids, f"{beat['id']}: on_silence {asks['on_silence']!r} is not an outcome"
        if asks["kind"] == "side":
            assert set(outcome_ids) <= {"julian", "mia", "neutral"}, beat["id"]
        else:
            defaults = [o for o in beat["outcomes"] if not o.get("when")]
            assert len(defaults) == 1 and beat["outcomes"][-1] is defaults[0], f"{beat['id']}: exactly one default outcome, last"


def test_must_follow_and_ending_ranks_match_the_table():
    must = {b["id"]: b["must_follow"]["rank"] for b in BEATS if "must_follow" in b}
    assert must == EXPECTED_MUST_FOLLOW
    ranks = {b["id"]: b["ending_rank"] for b in BEATS if b["type"] == "ending"}
    assert ranks == EXPECTED_ENDING_RANK


def test_tension_effect_is_half_the_slope():
    for b in BEATS:
        eff = b["effects"].get("tension")
        if b["type"] == "ending" or b["id"] == "the_door":
            continue
        assert eff is not None and float(eff) == b["tension_slope"] * 0.5, b["id"]


# --------------------------------------------------------------------------- reactions
REACTIONS_SCHEMA = load_json(SCHEMAS / "data" / "reactions.json")


def test_reactions_validate():
    assert errors(REACTIONS_SCHEMA, REACTIONS) == []
    ids = [r["id"] for r in REACTIONS["rules"] + REACTIONS["reactions"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("item", REACTIONS["rules"] + REACTIONS["reactions"], ids=lambda r: r["id"])
def test_reaction_rules_compile_and_effects_are_valid(item: dict[str, Any]):
    check_rule(item["when"], item["id"])
    check_effects(item.get("effects"), item["id"])


def test_every_topic_has_three_tiers_within_the_phase_caps():
    tiers: dict[str, set[int]] = {}
    for r in REACTIONS["reactions"]:
        if r["type"] == "topic":
            tiers.setdefault(r["topic"], set()).add(r["tier"])
            assert r["effects"][f"topic_tier.{r['topic']}"] == r["tier"], r["id"]
            if r["tier"] == 2:
                assert "story_phase != 'early'" in r["when"], r["id"]
            if r["tier"] == 3:
                assert "story_phase == 'late'" in r["when"], r["id"]
    assert tiers == {t: {1, 2, 3} for t in REACTIONS["topic_owner"]}


def test_revealed_only_changes_where_the_design_allows():
    """interaction-design.md §5.4: only beats and named tiers add facts; here only money tier 3."""
    allowed = {"money_t3"}
    for r in REACTIONS["rules"] + REACTIONS["reactions"]:
        if "revealed" in (r.get("effects") or {}):
            assert r["id"] in allowed, r["id"]


# --------------------------------------------------------------------------- replay
COMPILED: dict[str, Any] = {}


def holds(src: str | None, state: dict[str, Any], turn: dict[str, Any]) -> bool:
    if not src:
        return True
    node = COMPILED.setdefault(src, compile_expr(src))
    return bool(truthy(node, {**state, "turn": turn}))


def phase_of(story_min: float) -> str:
    ph = CLOCK["phases"]
    if story_min < ph["early"]["until_min"]:
        return "early"
    if story_min < ph["mid"]["until_min"]:
        return "mid"
    return "late"


def completed(state: dict[str, Any], beat_id: str) -> bool:
    return any(h["beat_id"] == beat_id and h["completed"] for h in state["beat_history"])


def entry_of(beat: dict[str, Any], state: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any] | None:
    return next((e for e in beat["entries"] if holds(e.get("when"), state, turn)), None)


def eligible(state: dict[str, Any], turn: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        b for b in BEATS
        if not completed(state, b["id"]) and holds(b["preconditions"], state, turn) and entry_of(b, state, turn)
    ]


def must_follow(state: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any] | None:
    hits = [b for b in eligible(state, turn) if b.get("must_follow") and holds(b["must_follow"]["when"], state, turn)]
    return min(hits, key=lambda b: b["must_follow"]["rank"]) if hits else None


def pick_ending(state: dict[str, Any], turn: dict[str, Any]) -> str | None:
    m = must_follow(state, turn)
    if m and m["type"] == "ending":
        return m["id"]
    ends = [b for b in eligible(state, turn) if b["type"] == "ending"]
    return min(ends, key=lambda b: b["ending_rank"])["id"] if ends else None


def apply(state: dict[str, Any], effects: dict[str, Any] | None) -> dict[str, Any]:
    return apply_effects(state, effects or {}, STATE_PROPS)


def finish_beat(state: dict[str, Any], beat: dict[str, Any], outcome: str | None) -> dict[str, Any]:
    state = apply(state, beat["effects"])
    if outcome:
        chosen = next(o for o in beat["outcomes"] if o["id"] == outcome)
        state = apply(state, chosen.get("effects"))
    state["beat_history"] = [*state["beat_history"], {"beat_id": beat["id"], "origin": "authored", "completed": True}]
    before = state["story_min"]
    state["story_min"] = round(before + beat.get("minutes", CLOCK["phases"][phase_of(before)]["default_minutes"]), 2)
    for ev in CLOCK["events"]:
        if before < ev["at_min"] <= state["story_min"]:
            state = apply(state, ev["effects"])
    state["story_phase"] = phase_of(state["story_min"])
    return state


GOLDEN = load_yaml(FIXTURES / "golden_path.yaml")


def test_golden_path_replays():
    state = default_state()
    for i, step in enumerate(GOLDEN):
        turn = {"acts": [], "topics": [], "claims": [], "action": None, **(step.get("turn") or {})}
        state = apply(state, step.get("patch"))
        if "ending" in step:
            assert pick_ending(state, turn) == step["ending"], f"step {i}: wrong ending"
            break
        ids = [b["id"] for b in eligible(state, turn)]
        assert step["beat"] in ids, f"step {i}: {step['beat']} not eligible; eligible = {ids}"
        forced = must_follow(state, turn)
        if forced:
            assert forced["id"] == step["beat"], f"step {i}: must-follow {forced['id']} preempts {step['beat']}"
        beat = BY_ID[step["beat"]]
        if "entry" in step:
            assert entry_of(beat, state, turn)["id"] == step["entry"], f"step {i}: wrong entry"
        state = apply(state, step.get("mix_in_effects"))
        state = finish_beat(state, beat, step.get("outcome"))
        assert state["story_min"] == step["min_after"], f"step {i}: story_min {state['story_min']} != {step['min_after']}"
        assert errors(STATE, state) == [], f"step {i}: invalid state"
    else:
        pytest.fail("golden path has no ending step")


def test_golden_path_matches_beat_script_order():
    assert [s.get("beat") or s.get("ending") for s in GOLDEN] == [
        "the_door", "dinner_on_the_crate", "the_fourth_setting", "mia_in_the_kitchen", "julian_on_the_balcony",
        "two_afternoons", "noras_call", "the_buzz", "the_admission", "the_versions", "downstairs", "the_offer",
        "the_knock", "testimony", "open_it",
    ]


def after_testimony(**patch: Any) -> dict[str, Any]:
    s = default_state(story_min=18.5, story_phase="late", nora_pressure=4, nora_room="living")
    s["beat_history"] = [{"beat_id": b, "origin": "authored", "completed": True} for b in ("the_knock", "testimony")]
    s.update(patch)
    return s


ENDING_CASES = [
    ("confession_mia", after_testimony(mia_composure=0.1, side=1.5, nora_told="none", revealed=["leo_dead"]), {}, "confession"),
    ("confession_julian", after_testimony(julian_composure=0.1, side=-1.5, nora_told="truth", revealed=["leo_dead"]), {}, "confession"),
    ("open_it", after_testimony(nora_told="truth", revealed=["leo_dead"]), {}, "open_it"),
    ("open_it_by_guessing", after_testimony(nora_told="truth"), {}, "open_it"),
    ("the_witness", after_testimony(nora_told="lie", revealed=["leo_dead"]), {}, "the_witness"),
    ("the_witness_silent", after_testimony(nora_told="none", revealed=["leo_dead"]), {}, "the_witness"),
    ("bon_voyage_never_knew", after_testimony(nora_told="none"), {}, "bon_voyage"),
    ("bon_voyage_left_early", default_state(player_room="outside", mia_room="living", story_min=7.5, story_phase="mid"), {}, "bon_voyage"),
    ("open_it_police", default_state(police_called=True, player_room="living", story_min=12.0, story_phase="late"), {}, "open_it"),
    (
        "second_crate",
        default_state(player_room="balcony", julian_room="balcony", mia_room="kitchen", julian_composure=0.1, side=1.6,
                      story_min=13.0, story_phase="late", threatened_julian=True),
        {"acts": ["threaten_to_tell"], "addressee": "julian"},
        "second_crate",
    ),
    (  # plan.md R18: the threat was made earlier; being alone with him now is enough
        "second_crate_threatened_before",
        default_state(player_room="balcony", julian_room="balcony", mia_room="kitchen", julian_composure=0.1, side=1.6,
                      story_min=13.0, story_phase="late", threatened_julian=True),
        {"acts": ["ask_about_leo"], "addressee": "julian"},
        "second_crate",
    ),
]


@pytest.mark.parametrize("state,turn,expected", [c[1:] for c in ENDING_CASES], ids=[c[0] for c in ENDING_CASES])
def test_every_ending_is_reachable(state: dict[str, Any], turn: dict[str, Any], expected: str):
    assert errors(STATE, state) == []
    t = {"acts": [], "topics": [], "claims": [], "action": None, **turn}
    assert pick_ending(deepcopy(state), t) == expected


def test_no_ending_before_testimony_without_a_trigger():
    s = default_state(story_min=14.0, story_phase="late", revealed=["leo_dead"], nora_told="truth")
    t = {"acts": [], "topics": [], "claims": [], "action": None}
    assert pick_ending(s, t) is None


# --------------------------------------------------------------------------- no dead ends
def random_walk(seed: int) -> tuple[str, list[str]]:
    """Random choices among eligible beats and outcomes, a random answer to Nora's call, and
    fast-forward over gaps (clock.yaml). Returns the ending and the beats played."""
    import random

    rng = random.Random(seed)
    state, played = default_state(), []
    for _ in range(80):
        turn = {"acts": [], "topics": [], "claims": [], "action": None, "nora_answer": rng.choice(["truth", "lie", "none"])}
        if state["nora_call"] == "ringing":  # the call turn picked no beat; this turn the player decides
            state = apply(state, rng.choice([{"nora_call": "answered"}, {"nora_call": "declined", "leo_phone": "buzzed"},
                                             {"nora_call": "missed", "leo_phone": "buzzed"}]))
        ending = pick_ending(state, turn)
        if ending:
            return ending, played
        forced = must_follow(state, turn)
        options = [b for b in eligible(state, turn) if b["type"] != "ending"]
        if forced:
            beat = forced
        elif options:
            beat = rng.choice(options)
        else:
            pending = [e for e in CLOCK["events"] if e["at_min"] > state["story_min"]]
            assert pending, f"seed {seed}: dead end at story_min {state['story_min']} after {played}"
            ev = pending[0]
            state = apply({**state, "story_min": ev["at_min"], "story_phase": phase_of(ev["at_min"])}, ev["effects"])
            continue
        outcomes = beat.get("outcomes") or []
        state = finish_beat(state, beat, rng.choice(outcomes)["id"] if outcomes else None)
        played.append(beat["id"])
        assert errors(STATE, state) == [], f"seed {seed}: invalid state after {played}"
    pytest.fail(f"seed {seed}: no ending after {played}")


def test_random_walks_never_dead_end_and_reach_several_endings():
    endings = {random_walk(seed)[0] for seed in range(300)}
    assert {"bon_voyage", "the_witness", "open_it"} <= endings, endings


# --------------------------------------------------------------------------- conditional lines (plan.md R26)
POOL = BeatPool.from_dir(DATA / "beats", set(STATE_PROPS))
#: a stage direction that hides a branch: "If couple_unity < 2:", "Unless ...:", "Or Julian:", "Left early:"
CONDITION_PROSE = re.compile(r"\b(If|Unless|Otherwise)\b[^.]*?(:|<|>|==)|\bOr (Julian|Mia|Nora):|Left early:")


def _unquoted(text: str) -> str:
    """Sample dialogue may say 'If you hear from him'; only the stage direction around it counts."""
    return re.sub(r"'[^']*'", "''", text)


@pytest.mark.parametrize("beat_id", sorted(POOL.by_id))
def test_no_step_hides_a_branch_in_its_prose(beat_id: str):
    for step in POOL.by_id[beat_id].steps:
        for text in [step["do"], *(ln["do"] for ln in step.get("lines") or [])]:
            assert not CONDITION_PROSE.search(_unquoted(text)), f"{beat_id}.{step['id']}: write the branch as `lines`: {text!r}"


def test_lines_resolve_against_the_state():
    offer = next(b for b in POOL.beats if any(s["id"] == "the_leverage" for s in b.steps))
    step = [s for s in offer.steps if s["id"] == "the_leverage"]
    heard = offer.resolve(step, rule_ctx(default_state(heard_by={"missed_call": ["julian", "mia"]}), {}))[0]
    unheard = offer.resolve(step, rule_ctx(default_state(), {}))[0]
    assert "Two missed calls" in heard["do"] and "ate off that crate" not in heard["do"] and "lines" not in heard
    assert "ate off that crate" in unheard["do"]

    open_it = POOL.by_id["open_it"]
    edge = default_state(police_called=True, mia_composure=0.1, side=1.5, couple_unity=3)
    text = " ".join(s["do"] for s in open_it.resolve(open_it.steps, rule_ctx(edge, {})))
    assert "The screws come out" in text and "already said it" in text and "throat" not in text and "Ask her" not in text
    late = default_state(nora_told="truth", mia_composure=0.2, side=1.5, couple_unity=1, crate="opened")
    text = " ".join(s["do"] for s in open_it.resolve(open_it.steps, rule_ctx(late, {})))
    assert "already off" in text and "throat" in text and "Ask her" in text
