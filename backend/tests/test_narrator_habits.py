"""Character habits with a budget (engine/narrator/knowledge.py): the opening gets no tells, a counted habit stops
being handed to the narrator once used, and a beat step line can read what has been used. The motivating case:
Mia asked "Did you come by car?" in the opening passage and again in the first beat's own step (pilot sessions)."""

from __future__ import annotations

from app.session import Session
from engine.beats import rule_ctx
from engine.narrator import Knowledge

KNOW = Knowledge.from_dir()
STATE = {"revealed": [], "tells_used": []}
SPEAKERS = ["julian", "mia"]


def persona(state: dict, who: str = "mia", opening: bool = False) -> dict:
    return KNOW.slice(state, SPEAKERS, [], opening=opening)[who]["persona"]


def has_text(items: list[str], needle: str) -> bool:
    return any(needle in x for x in items)


def seg(kind: str, text: str, speaker: str | None = None) -> dict:
    return {"kind": kind, "text": text, **({"speaker": speaker} if speaker else {})}


def test_the_opening_passage_gets_no_tells_but_keeps_the_background():
    p = persona(STATE, opening=True)
    assert "tells" not in p and has_text(p["background"], "corner of the kitchen island")
    assert has_text(persona(STATE)["tells"], "Did you come by car")


def test_a_habit_leaves_the_card_once_it_has_used_up_its_budget():
    used = lambda *ids: {**STATE, "tells_used": list(ids)}  # noqa: E731
    assert not has_text(persona(used("car_question"))["tells"], "by car")  # max_uses 1
    assert has_text(persona(used("leo_past_tense"))["tells"], "past tense")  # max_uses 2: one use left
    assert not has_text(persona(used("leo_past_tense", "leo_past_tense"))["tells"], "past tense")
    assert has_text(persona(used("wipes_corner", "wipes_corner"))["background"], "corner of the kitchen island")
    assert not has_text(persona(used(*["wipes_corner"] * 3))["background"], "corner of the kitchen island")
    # a plain-string habit has no budget; the other characters' cards are untouched
    assert has_text(persona(used("car_question"))["background"], "far end")
    assert has_text(persona(used(*["checks_watch"] * 4), "julian")["background"], "jacket")
    assert not has_text(persona(used(*["checks_watch"] * 4), "julian")["background"], "watch")


def test_used_in_reads_the_finished_passage_and_ignores_the_players_own_lines():
    mia = [seg("speech", "Did you drive? Where did you park?", "mia"), seg("narration", "She wipes the clean corner of the island again.")]
    assert set(KNOW.used_in(mia)) == {"car_question", "wipes_corner"}
    echoed = [seg("me", "I tell her I came by car."), seg("me_speech", "Did you drive?")]
    assert KNOW.used_in(echoed) == []
    julian = [seg("narration", "Julian turns his wrist and checks his watch; he tops up a glass that was already full.")]
    assert set(KNOW.used_in(julian)) == {"checks_watch", "pours_full"}


def test_every_habit_id_is_unique_and_every_pattern_matches_a_sample_of_its_own_wording():
    samples = {
        "car_question": "Did you come by car?", "leo_past_tense": "He was always... is always late.", "wipes_corner": "wipes the same clean corner",
        "checks_windows": "she checks the window catch", "pours_full": "he tops up her glass", "checks_watch": "he checks his watch",
    }
    assert set(KNOW.habits) == set(samples)
    for hid, text in samples.items():
        assert KNOW.habits[hid][0].search(text), hid


def test_the_arrival_step_asks_about_the_car_only_if_nobody_has_yet():
    from engine.beats import BeatPool
    from engine.paths import DATA_DIR
    from engine.state import StateSchema

    schema = StateSchema()
    door = BeatPool.from_dir(DATA_DIR / "beats", set(schema.props)).by_id["the_door"]
    step = [s for s in door.steps if s["id"] == "julian_with_wine"]

    def text(used: list[str]) -> str:
        state = {**schema.initial_state(), "tells_used": used}
        return door.resolve(step, rule_ctx(state, {}))[0]["do"]

    assert "Did you drive? Where did you park?" in text([])
    assert "Did you drive" not in text(["car_question"]) and "puts a glass in your hand" in text(["car_question"])


async def play_door(preset: list[str]) -> tuple[Session, list[str]]:
    s = Session("habits", seed=1, scorer="rule", save_generated=False)
    await s.start("Sam", "female")
    await s.control("set_state", {"patch": {"tells_used": preset}})
    passages = []
    for line in ("I take off my coat.", "I look around the flat."):
        await s.submit({"speech": "", "action": line, "expression": "", "addressee": None}, "filled")
        passages.append(" ".join(g["text"] for g in s.passages[-1]["segments"]))
    return s, passages


async def test_a_session_asks_about_the_car_once_and_books_it():
    s, passages = await play_door([])
    assert sum("Did you drive" in p for p in passages) == 1
    assert s.state["tells_used"].count("car_question") == 1
    assert "tells_used" not in s.schema.textualize(s.state)  # bookkeeping: not part of the scorers' state text
    assert "tells_used" in s.logger.read_turns()[-1]["state"]


async def test_when_the_question_was_already_asked_the_step_does_not_repeat_it():
    s, passages = await play_door(["car_question"])
    assert not any("Did you drive" in p for p in passages)
    assert any("puts a glass in your hand" in p for p in passages)
    assert s.state["tells_used"].count("car_question") == 1
