from pathlib import Path

import pytest

import engine.state.schema as state_schema
from engine.dsl import DSLSyntaxError, apply_effects, compile_expr, evaluate, referenced_vars, truthy
from engine.state import StateSchema


@pytest.fixture(autouse=True)
def wrongest_person_state_v1(monkeypatch):
    """The DSL tests were written against Wrongest Person's state_v1 (copied to tests/fixtures/); they test
    the DSL, not Fragile's story, so they keep that schema."""
    monkeypatch.setattr(state_schema, "SCHEMAS_DIR", Path(__file__).parent / "fixtures")


@pytest.fixture
def state():
    # Wrongest Person's opening situation (its state_v1 has no defaults to build it from)
    return {
        "schema_version": 1, "tension": 2, "lin_composure": 1.0, "may_suspicion": 0, "may_trust_lin": 1,
        "danger_proximity": 0, "guest_pressure": 0, "revealed": ["debt"], "glass": "on_table", "gun": "hidden",
        "envelope": "sealed", "door": "closed", "may_zone": "guest_table", "lin_zone": "guest_table",
        "guest_zone": "absent", "beat_history": [], "consecutive_generated": 0, "story_phase": "early",
        "clock_s": 0.0, "ending": None, "last_discourse_act": None, "last_interaction": None,
    }


def test_compile_basic_and_in(state):
    rule = compile_expr("may_zone in [guest_table, bar] and glass == 'on_table'")
    assert rule == {"and": [{"in": [{"var": "may_zone"}, ["guest_table", "bar"]]}, {"==": [{"var": "glass"}, "on_table"]}]}
    assert truthy(rule, state)


def test_not_in_and_membership(state):
    assert truthy(compile_expr("'gun' not in revealed"), state)
    assert truthy(compile_expr("'debt' in revealed"), state)
    assert not truthy(compile_expr("'debt' not in revealed"), state)


def test_count_and_comparisons(state):
    assert truthy(compile_expr("count(beat_history) == 0"), state)
    assert truthy(compile_expr("tension >= 2 and tension < 3"), state)
    assert evaluate(compile_expr("tension + 1 - 3"), state) == 0


def test_near_uses_names_not_values(state):
    state["lin_zone"] = "guest_table"
    assert truthy(compile_expr("near(may, lin)"), state)
    assert truthy(compile_expr("near(may, poisoned_glass)"), state)
    state["may_zone"] = "bar"
    assert not truthy(compile_expr("near(may, lin)"), state)


def test_played(state):
    state["beat_history"] = [{"beat_id": "the_trap", "origin": "authored"}]
    assert truthy(compile_expr("played('the_trap')"), state)
    assert not truthy(compile_expr("played('the_man')"), state)


def test_literals_and_empty():
    assert compile_expr("true") is True
    assert compile_expr("") is True
    assert compile_expr(None) is True
    assert evaluate(compile_expr("not false"), {}) is True


def test_unknown_function_rejected():
    with pytest.raises(DSLSyntaxError):
        compile_expr("exec('rm -rf /')")
    with pytest.raises(DSLSyntaxError):
        compile_expr("tension == = 2")


def test_referenced_vars():
    rule = compile_expr("may_zone == 'bar' and count(beat_history) > 1 and 'gun' in revealed")
    assert referenced_vars(rule) == {"may_zone", "beat_history", "revealed"}


def test_apply_effects_clamps_and_validates(state):
    props = StateSchema(1).props
    new = apply_effects(state, {"tension": "+9", "lin_composure": "-0.25", "glass": "moved", "revealed": ["add", "gun"]}, props)
    assert new["tension"] == 5
    assert new["lin_composure"] == 0.75
    assert new["glass"] == "moved"
    assert new["revealed"] == ["debt", "gun"]
    assert state["tension"] == 2  # original untouched
    with pytest.raises(ValueError):
        apply_effects(state, {"glass": "evaporated"}, props)
    with pytest.raises(KeyError):
        apply_effects(state, {"mood": "+1"}, props)
