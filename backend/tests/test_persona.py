"""The self-play persona generator (selfplay.md §3 to §5): sampling, weights, axes, rendering."""

from __future__ import annotations

import random
import re

import pytest
from helpers import BACKEND

from engine.models.guard import FACT_PATTERNS
from selfplay.persona import PersonaGenerator, correlation

GEN = PersonaGenerator()
MANY = GEN.generate(4000, seed=11)


def test_same_seed_same_personas_and_different_seeds_differ():
    a = [p.to_json() for p in GEN.generate(20, seed=3)]
    b = [p.to_json() for p in GEN.generate(20, seed=3)]
    c = [p.to_json() for p in GEN.generate(20, seed=4)]
    assert a == b and a != c


def test_tail_share_and_importance_weights():
    tails = sum(bool(p.sampling["tail"]) for p in MANY) / len(MANY)
    assert tails == pytest.approx(GEN.tail_fraction, abs=0.03)
    # importance weights average to one: the sample reweights back to the population
    assert sum(p.sampling["weight"] for p in MANY) / len(MANY) == pytest.approx(1.0, abs=0.03)
    for p in MANY:
        for dim, side in p.sampling["tail"]:
            z = p.hexaco[dim]
            # hexaco values are stored to three decimals
            assert (z > GEN.cut - 1e-3) if side == "high" else (z < -GEN.cut + 1e-3)


def test_weighted_sample_recovers_the_population_correlations():
    rows = [[p.hexaco[d] for d in GEN.dims] for p in MANY]
    w = [p.sampling["weight"] for p in MANY]
    for i in range(len(GEN.dims)):
        for j in range(i + 1, len(GEN.dims)):
            assert correlation(rows, i, j, w) == pytest.approx(GEN.corr[i][j], abs=0.07), (GEN.dims[i], GEN.dims[j])


def test_axes_ranges_and_the_leave_coefficient():
    for p in MANY:
        assert all(0 <= v <= 1 for v in p.axes_raw.values())
        assert p.axes["leave"] <= 0.1 + 1e-9 and p.axes["violation_rate"] <= 0.15 + 1e-9
    high_leave = sum(GEN.bucket("leave", p.axes_raw["leave"]) == "high" for p in MANY) / len(MANY)
    assert high_leave == pytest.approx(0.10, abs=0.03)


def test_leaving_goals_are_rare_without_inflating_staying():
    count = {g: sum(p.goal == g for p in MANY) for g in ("early_night", "escape_awkward", "stay_till_end")}
    share = 1 / len(GEN.goals)
    # the leave x 0.1 coefficient keeps these well below an average goal's share
    assert count["early_night"] / len(MANY) < share / 2 and count["escape_awkward"] / len(MANY) < share / 2
    assert count["stay_till_end"] / len(MANY) < share * 2


def _with(axes: dict[str, float], hexaco: dict[str, float] | None = None):
    """A persona whose axes are set by hand, rendered again."""
    p = GEN.generate_one(seed=99, index=0)
    p.axes_raw = {**{a: 0.5 for a in p.axes_raw}, **axes}
    p.hexaco = hexaco or {d: 0.0 for d in GEN.dims}
    p.card = GEN.render(p, random.Random(0))
    return p


def _rules_text(axis: str, bucket: str) -> list[str]:
    return GEN.rules["rules"][axis][bucket]


def test_archetypes_render_as_themselves():
    detective = _with({"curiosity": 0.95})
    assert any(t in detective.card for t in _rules_text("curiosity", "high"))
    provocateur = _with({"confrontation": 0.95, "compliance": 0.05})
    assert any(t in provocateur.card for t in _rules_text("confrontation", "high"))
    assert any(t in provocateur.card for t in _rules_text("compliance", "low"))
    polite = _with({"curiosity": 0.1, "confrontation": 0.1, "compliance": 0.9})
    combo = next(c for c in GEN.rules["combos"] if c["when"] == {"curiosity": "low", "confrontation": "low"})
    assert any(t in polite.card for t in combo["text"])
    assert not any(t in polite.card for t in _rules_text("curiosity", "low"))  # replaced by the combo
    leaver = _with({"leave": 0.95})
    assert any(t in leaver.card for t in _rules_text("leave", "high"))
    almost = _with({"leave": 0.85})  # high on a 0..1 axis, but not in the top 10% the 0.1 coefficient allows
    assert not any(t in almost.card for t in _rules_text("leave", "high"))


def test_cards_are_short_and_carry_no_numbers_unless_asked():
    for p in MANY[:300]:
        assert len(GEN._rules(p, random.Random(0))) <= GEN.cfg["max_rules"]
        assert not re.search(r"\d", " ".join(p.card).replace("07:40", ""))
    numeric = GEN.generate_one(seed=5, index=1, render="numeric")
    assert re.search(r"H [+-]\d\.\d", numeric.card[0]) and "You are" not in numeric.card[0]
    assert len({tuple(p.card) for p in MANY}) > 0.95 * len(MANY)


def test_nothing_the_player_is_told_gives_the_story_away():
    texts = [g["text"] for g in GEN.goals]
    texts += [t for rule in GEN.rules["rules"].values() for bucket in rule.values() for t in bucket]
    texts += [t for c in GEN.rules["combos"] for t in c["text"]]
    texts += [t for side in GEN.rules["side"].values() for bucket in side.values() for t in bucket]
    texts += [t for stance in GEN.rules["stance"].values() for t in stance]
    known_walking_in = {"missed_call"}  # the player card says Leo called twice (data/knowledge/player.yaml)
    for t in texts:
        hits = [f for f, pat in FACT_PATTERNS.items() if pat.search(t) and f not in known_walking_in]
        assert not hits, (t, hits)
        assert not re.search(r"\b(dead|body|corpse|killed|murder)\b", t, re.I), t


def test_config_is_consistent():
    axes = set(GEN.cfg["axes"])
    for g in GEN.goals:
        assert set(g["affinity"]) <= axes, g["id"]
    assert len({g["id"] for g in GEN.goals}) == len(GEN.goals) >= 30
    assert set(GEN.rules["rules"]) <= axes
    for c in GEN.rules["combos"]:
        assert set(c["when"]) <= axes and set(c["replaces"]) <= set(c["when"])


#: words that tell the player something is wrong before the story does
PRIMING = re.compile(r"\b(terrible|wrong|lie|lies|lying|liar|hiding|hidden|secret|secrets|mystery|crime|suspect|police|murder|dead|died|missing|going on|uneasy|unsettling|suspicious|ominous|strange)\b", re.I)


def test_the_opening_card_and_the_player_prompt_hint_at_nothing():
    """A persona says who the player is, not what happens tonight (selfplay.md §3.4)."""
    for p in MANY[:1000]:
        for line in p.card:
            assert not PRIMING.search(line), line
    for g in GEN.goals:
        assert not PRIMING.search(g["text"]), g["text"]
    prompt = (BACKEND / "prompts" / "selfplay_v1.md").read_text(encoding="utf-8").split("# Personas")[0]
    assert not PRIMING.search(prompt), PRIMING.search(prompt)


def test_the_stance_joins_the_card_only_once_the_truth_is_out():
    p = GEN.generate_one(seed=7, index=3)
    before = GEN.card_at(p, {"revealed": ["missed_call", "car_downstairs"]})
    after = GEN.card_at(p, {"revealed": ["missed_call", "leo_dead"]})
    assert before == p.card and after == p.card + p.triggered["truth_out"]
    assert all(line.startswith("Now that you know") for line in p.triggered["truth_out"])


def test_the_stance_follows_honesty():
    honest = [p for p in MANY if p.axes["honesty_to_nora"] > 0.8]
    dishonest = [p for p in MANY if p.axes["honesty_to_nora"] < 0.2]
    report = lambda ps: sum(p.stance == "report" for p in ps) / len(ps)  # noqa: E731
    assert report(honest) > 0.6 and report(dishonest) < 0.05
