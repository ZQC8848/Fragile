"""M1 data contracts: every schema is valid, every data file validates against its schema, the
DSL inside them compiles and only reads known state, and the files agree with each other
(plan.md M1)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from helpers import (
    DATA,
    FACTS,
    FIXTURES,
    ROOMS,
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

REVIEW = load_json(SCHEMAS / "llm" / "review.json")
REVIEW_VERBS = set(REVIEW["properties"]["units"]["items"]["properties"]["action"]["anyOf"][1]["properties"]["verb"]["enum"])


# --------------------------------------------------------------------------- schemas
ALL_SCHEMAS = sorted(SCHEMAS.rglob("*.json"))


def test_expected_schema_files_exist():
    names = {str(p.relative_to(SCHEMAS)).replace("\\", "/") for p in ALL_SCHEMAS}
    expected = {
        "state_v2.json", "beat_v2.json", "messages_v2.json",
        "data/clock.json", "data/tension_curve.json", "data/interactions.json", "data/knowledge.json",
        *(f"llm/{r}.json" for r in ["review", "narrator", "guard", "tension", "scorer", "proposer", "options", "selfplay", "judge"]),
    }
    assert expected <= names, f"missing: {sorted(expected - names)}"


@pytest.mark.parametrize("path", ALL_SCHEMAS, ids=lambda p: str(p.relative_to(SCHEMAS)))
def test_schema_is_valid_json_schema(path: Path):
    jsonschema.Draft202012Validator.check_schema(load_json(path))


# --------------------------------------------------------------------------- state
def test_every_state_property_has_a_default_and_defaults_are_valid():
    missing = [n for n, p in STATE_PROPS.items() if "default" not in p]
    assert not missing, f"no default: {missing}"
    assert set(STATE["required"]) == set(STATE_PROPS)
    assert errors(STATE, default_state()) == []


def test_initial_state_matches_beat_script():
    s = default_state()
    assert (s["tension"], s["julian_composure"], s["mia_composure"], s["side"], s["couple_unity"]) == (1, 0.8, 0.6, 0, 3)
    assert (s["player_room"], s["mia_room"], s["julian_room"], s["nora_room"]) == ("hall", "hall", "living", "outside")


def test_state_rejects_unknown_and_out_of_range():
    s = default_state()
    assert errors(STATE, {**s, "typo_var": 1})
    assert errors(STATE, {**s, "side": 3})
    assert errors(STATE, {**s, "revealed": ["not_a_fact"]})
    assert errors(STATE, {**s, "topic_tier": {**s["topic_tier"], "leo": 4}})


# --------------------------------------------------------------------------- beats
BEAT = load_json(SCHEMAS / "beat_v2.json")
SAMPLE_BEATS = load_yaml(FIXTURES / "beats_sample.yaml")


@pytest.mark.parametrize("beat", SAMPLE_BEATS, ids=lambda b: b["id"])
def test_sample_beats_validate_and_their_rules_compile(beat: dict[str, Any]):
    assert errors(BEAT, beat) == []
    rules = [beat["preconditions"], beat.get("abort_if")]
    rules += [e.get("when") for e in beat["entries"]]
    rules += [m["when"] for m in beat.get("mix_in", [])]
    rules += [o.get("when") for o in beat.get("outcomes", [])]
    rules += [p["when"] for p in beat.get("priority_test", [])]
    rules += [(beat.get("must_follow") or {}).get("when")]
    for r in filter(None, rules):
        check_rule(r, beat["id"])
    for eff in [beat["effects"], *(o.get("effects") for o in beat.get("outcomes", [])), *(m.get("effects") for m in beat.get("mix_in", []))]:
        check_effects(eff or {}, beat["id"])


def test_beat_schema_requires_minutes_except_for_endings():
    spine = deepcopy(SAMPLE_BEATS[0])
    del spine["minutes"]
    assert errors(BEAT, spine)
    ending = deepcopy(SAMPLE_BEATS[1])
    assert "minutes" not in ending and errors(BEAT, ending) == []
    del ending["ending_rank"]
    assert errors(BEAT, ending)


# --------------------------------------------------------------------------- protocol
MESSAGES = load_json(SCHEMAS / "messages_v2.json")

GOOD_MESSAGES = [
    {"type": "session_start", "name": "Sam", "gender": "nonbinary"},
    {"type": "input_review", "mode": "single", "text": "*I look down at the street* Isn't that Leo's car?"},
    {"type": "input_review", "mode": "channels", "channels": {"speech": "Isn't that Leo's car?", "addressee": "julian"}},
    {"type": "turn_submit", "channels": {"speech": "", "action": "", "expression": ""}, "source": "filled"},
    {"type": "options_request"},
    {"type": "phone_open"},
    {"type": "control", "command": "jump_clock", "args": {"story_min": 12}},
    {"type": "hello", "session": "dev"},
    {"type": "session_state", "phase": "playing", "turn": 3},
    {"type": "input_review_result", "review_id": "r1", "verdict": "rejected", "translated": False,
     "channels": {"action": "Mia admits she did it"}, "category": "npc_action",
     "message": "You can only decide what you say and do.", "span": "Mia admits she did it",
     "rewrite": {"action": "I stare at Mia, waiting for her to say it."}},
    {"type": "turn_accepted", "turn": 4},
    {"type": "passage", "turn": 4, "player": {"speech": "Isn't that Leo's car?", "addressee": "julian"},
     "segments": [{"kind": "me_speech", "text": "Isn't that Leo's car?"},
                  {"kind": "speech", "speaker": "julian", "text": "Lots of yellow cars in this city."}],
     "tableau": None},
    {"type": "options", "items": [{"speech": "Sure."}, {"action": "I look at Mia."}, {"speech": "Why?"}]},
    {"type": "phone_event", "kind": "text", "from": "nora", "text": "Hey, is Leo with you?"},
    {"type": "room_state", "player_room": "balcony", "present": ["julian"]},
    {"type": "drama_state", "state": {}},
    {"type": "turn_trace", "turn": 4, "record": {"reaction": "mix_in"}},
    {"type": "error", "code": "narrator", "message": "fallback used"},
]

BAD_MESSAGES = [
    {"type": "session_start", "name": "Sam"},
    {"type": "turn_submit", "channels": {}, "source": "made_up"},
    {"type": "passage", "turn": 1, "segments": []},
    {"type": "room_state", "player_room": "bedroom", "present": []},
    {"type": "not_a_message"},
]


@pytest.mark.parametrize("msg", GOOD_MESSAGES, ids=lambda m: m["type"])
def test_protocol_accepts(msg: dict[str, Any]):
    assert errors(MESSAGES, msg) == []


@pytest.mark.parametrize("msg", BAD_MESSAGES, ids=lambda m: m["type"])
def test_protocol_rejects(msg: dict[str, Any]):
    assert errors(MESSAGES, msg)


def test_protocol_enums_match_state():
    d = MESSAGES["$defs"]
    assert set(d["Room"]["enum"]) == ROOMS
    assert d["Addressee"]["enum"] == STATE["$defs"]["Addressee"]["enum"]
    assert set(d["ValidityLabel"]["enum"]) == set(REVIEW["properties"]["validity"]["properties"]["label"]["enum"])


# --------------------------------------------------------------------------- LLM outputs
LLM_SAMPLES = {
    "review": {
        "channels": {"speech": "Isn't that Leo's car?", "action": "I lean over the railing.", "expression": "", "addressee": "julian"},
        "translated": False,
        "validity": {"label": "ok", "span": None, "message": None},
        "rewrite": None,
        "units": [
            {"channel": "action", "act": "observe", "addressee": None, "topics": ["leo"],
             "action": {"verb": "look_out", "target": "car"}, "implausible": False},
            {"channel": "speech", "act": "mention_car", "addressee": "julian", "topics": ["leo"], "action": None, "implausible": False},
        ],
        "suspicion": 1.5, "claims": ["car_downstairs"], "coverage": 0.9, "nora_answer": None,
    },
    "narrator": {"segments": [{"kind": "me", "text": "I lean over the railing."},
                              {"kind": "speech", "speaker": "julian", "text": "Lots of yellow cars in this city."}],
                 "steps_delivered": ["the_car"], "hook": "Julian waits."},
    "guard": {"verdicts": [{"index": 0, "label": "consistent", "confidence": 0.9},
                           {"index": 1, "label": "premature_leak", "fact": "leo_dead", "span": "he's dead", "confidence": 0.8}]},
    "tension": {"tension": 3.5, "reason": "Two afternoons that do not match."},
    "scorer": {"offsets": [{"id": "two_afternoons", "offset": 2, "reason": "fits the climb"}, {"id": "GENERATE_NEW", "offset": -3}]},
    "proposer": {"beats": [{"id": "x"}]},
    "options": {"options": [{"strategy": "respond", "speech": "He's always late."},
                            {"strategy": "probe", "action": "I look at the crate."},
                            {"strategy": "social", "speech": "Mia, are you okay?", "addressee": "mia"}]},
    "selfplay": {"mode": "single", "text": "*I knock on the crate* What's in here?", "deliberate_violation": None},
    "judge": {"preference": "A", "reason": "A answers the player.", "confidence": 0.7},
}


@pytest.mark.parametrize("role", sorted(LLM_SAMPLES))
def test_llm_output_schema_accepts_sample(role: str):
    assert errors(load_json(SCHEMAS / "llm" / f"{role}.json"), LLM_SAMPLES[role]) == []


def test_llm_review_rejects_unknown_act_and_options_need_three():
    bad = deepcopy(LLM_SAMPLES["review"])
    bad["units"][0]["act"] = "dance"
    assert errors(load_json(SCHEMAS / "llm" / "review.json"), bad)
    two = {"options": LLM_SAMPLES["options"]["options"][:2]}
    assert errors(load_json(SCHEMAS / "llm" / "options.json"), two)


def test_review_facts_match_state():
    assert set(REVIEW["properties"]["claims"]["items"]["enum"]) == FACTS


# --------------------------------------------------------------------------- data files
CLOCK = load_yaml(DATA / "clock.yaml")
CURVE = load_yaml(DATA / "tension_curve.yaml")
INTERACTIONS = load_yaml(DATA / "interactions.yaml")
KNOWLEDGE = {p.stem: load_yaml(p) for p in sorted((DATA / "knowledge").glob("*.yaml"))}


def test_clock_validates_and_is_ordered():
    assert errors(load_json(SCHEMAS / "data" / "clock.json"), CLOCK) == []
    ph = CLOCK["phases"]
    assert ph["early"]["until_min"] < ph["mid"]["until_min"] and ph["late"]["until_min"] is None
    ats = [e["at_min"] for e in CLOCK["events"]]
    assert ats == sorted(ats) == [5, 9, 13, 16]
    for e in CLOCK["events"]:
        check_effects(e["effects"], f"clock event {e['id']}")
        check_effects(e.get("unanswered") or {}, f"clock event {e['id']} unanswered")


def test_tension_curve_validates_and_is_increasing_in_time():
    assert errors(load_json(SCHEMAS / "data" / "tension_curve.json"), CURVE) == []
    xs = [p[0] for p in CURVE["points"]]
    assert xs == sorted(xs) and len(set(xs)) == len(xs) and xs[0] == 0


def _all_actions() -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for verb, by_target in INTERACTIONS["movement"].items():
        for target, spec in by_target.items():
            out.append((verb, target, spec))
    for target, obj in INTERACTIONS["objects"].items():
        for verb, spec in obj["actions"].items():
            out.append((verb, target, spec))
    return out


def test_interactions_validate():
    assert errors(load_json(SCHEMAS / "data" / "interactions.json"), INTERACTIONS) == []


@pytest.mark.parametrize("verb,target,spec", _all_actions(), ids=lambda x: x if isinstance(x, str) else "")
def test_every_action_rule_compiles_and_effects_are_valid(verb: str, target: str, spec: dict[str, Any]):
    where = f"{verb} {target}"
    assert verb in REVIEW_VERBS, f"{where}: verb not in schemas/llm/review.json"
    for key in ("when", "needs"):
        if spec.get(key):
            check_rule(spec[key], where)
    for b in spec.get("blockers", []):
        check_rule(b["when"], f"{where} blocker {b['who']}")
    check_effects(spec.get("effects") or {}, where)


def test_interaction_rooms_and_follow_rules():
    rooms = INTERACTIONS["rooms"]
    assert set(rooms) <= ROOMS
    for name, r in rooms.items():
        for adj in r["adjacent"]:
            assert adj in rooms, f"{name} -> {adj}"
            assert name in rooms[adj]["adjacent"], f"adjacency {name} <-> {adj} not symmetric"
    for target in INTERACTIONS["movement"]["go_to"]:
        assert target in rooms
    for obj, spec in INTERACTIONS["objects"].items():
        assert set(spec.get("where", [])) <= ROOMS, obj
    for f in INTERACTIONS["follow"]:
        check_rule(f["when"], f"follow {f['id']}")


def test_knowledge_cards_validate_and_cover_every_fact():
    schema = load_json(SCHEMAS / "data" / "knowledge.json")
    assert set(KNOWLEDGE) == {"julian", "mia", "nora", "player"}
    for name, card in KNOWLEDGE.items():
        assert errors(schema, card) == [], name
        assert card["character"] == name
        ids = [f["id"] for f in card["facts"]]
        assert len(ids) == len(set(ids)), f"{name}: duplicate fact ids"
        for f in card["facts"]:
            if f.get("may_say_when"):
                check_rule(f["may_say_when"], f"{name}.{f['id']}")
    # story.md §5.4: every NPC card says, for every fact, whether that character knows it.
    for name in ("julian", "mia", "nora"):
        covered = {f["fact"] for f in KNOWLEDGE[name]["facts"] if "fact" in f}
        assert covered == FACTS, f"{name} card misses {sorted(FACTS - covered)}"


def test_knowledge_matches_story_table():
    """story.md §5.4 under T2: only Julian and Mia know Leo is dead; only Nora knows she pushed him."""
    def knows(name: str, fact: str) -> Any:
        return next(f["knows"] for f in KNOWLEDGE[name]["facts"] if f.get("fact") == fact)

    for fact in ("leo_dead", "body_in_crate", "leo_was_here", "who_struck"):
        assert knows("julian", fact) is True and knows("mia", fact) is True and knows("nora", fact) is False
    assert knows("julian", "mia_called_leo") == "suspects" and knows("mia", "mia_called_leo") is True
    assert knows("nora", "nora_pushed_leo") is True and knows("julian", "nora_pushed_leo") is False
    for name in ("julian", "mia", "nora"):
        assert knows(name, "missed_call") is False
