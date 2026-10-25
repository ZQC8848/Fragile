from ml.task2.common.align import align_tagged, assign_units, fuzzy_find, parse_tagged
from ml.task2.common.textnorm import normalize_with_map


def _texts(original, spans):
    return [(s.channel, original[s.start:s.end], s.unit) for s in spans]


def test_parse_tagged_plain_and_spans():
    plain, spans = parse_tagged('<A>I sit</A> <S i=0>"Hi."</S>')
    assert plain == 'I sit "Hi."'
    assert [(s.channel, plain[s.start:s.end], s.unit) for s in spans] == [("action", "I sit", None), ("speech", '"Hi."', 0)]


def test_quotes_are_trimmed_and_curly_quotes_match_straight():
    original = 'I put my glass down. “Where is he, Julian?”'
    tagged = '<A>I put my glass down.</A> <S i=0>"Where is he, Julian?"</S>'
    spans = align_tagged(original, tagged)
    assert _texts(original, spans) == [("action", "I put my glass down.", None), ("speech", "Where is he, Julian?", 0)]


def test_chinese_with_fullwidth_punctuation_and_mixed_script():
    original = "我盯着 Julian，问他：“Leo 下午来过吗？”"
    tagged = "<E>我盯着 Julian</E>，<A>问他</A>：<S i=0>“Leo 下午来过吗？”</S>"
    spans = align_tagged(original, tagged)
    assert _texts(original, spans) == [("expression", "我盯着 Julian", None), ("action", "问他", None), ("speech", "Leo 下午来过吗？", 0)]


def test_whitespace_differences_are_ignored():
    original = "I  lean over\nthe railing."
    spans = align_tagged(original, "<A>I lean over the railing.</A>")
    assert _texts(original, spans) == [("action", original, None)]


def test_echo_that_changes_words_is_rejected():
    assert align_tagged("I sit down.", "<A>I sat down.</A>") is None


def test_nested_or_unbalanced_tags_are_rejected():
    assert align_tagged("ab", "<A>a<S>b</S></A>") is None
    assert align_tagged("ab", "<A>ab</S>") is None


def test_interleaved_speech_units_by_index():
    original = '"Hi." I sit. "Is Leo here?"'
    tagged = '<S i=0>"Hi."</S> <A>I sit.</A> <S i=1>"Is Leo here?"</S>'
    spans = align_tagged(original, tagged)
    units = [{"channel": "speech", "act": "greet"}, {"channel": "speech", "act": "ask_about_leo"}, {"channel": "action", "act": "observe"}]
    placed, method = assign_units(original, spans, units)
    assert method == "indexed"
    assert [original[s:e] for s, e in placed] == ["Hi.", "Is Leo here?", "I sit."]


def test_unindexed_speech_falls_back_to_sentences_in_order():
    original = '"Hi Mia. Is Leo here yet?"'
    spans = align_tagged(original, '<S>"Hi Mia. Is Leo here yet?"</S>')
    units = [{"channel": "speech", "act": "greet"}, {"channel": "speech", "act": "ask_about_leo"}]
    placed, method = assign_units(original, spans, units)
    assert method == "ordered"
    assert [original[s:e] for s, e in placed] == ["Hi Mia.", "Is Leo here yet?"]


def test_unplaceable_speech_units_stay_none():
    original = '"Hi."'
    spans = align_tagged(original, '<S>"Hi."</S>')
    placed, method = assign_units(original, spans, [{"channel": "speech", "act": "greet"}, {"channel": "speech", "act": "ask"}])
    assert method == "unplaced" and placed == [None, None]


def test_fuzzy_find_exact_and_approximate():
    original = "I grab Julian's wrist. \"Show me the phone.\""
    s, e = fuzzy_find(original, "Show me the phone.")
    assert original[s:e] == "Show me the phone."
    s, e = fuzzy_find(original, "I grab Julians wrist")
    assert original[s:e].startswith("I grab Julian")
    assert fuzzy_find(original, "completely unrelated words here") is None


def test_normalize_map_points_back_to_original():
    text = "a　“b”"
    norm, idx = normalize_with_map(text)
    assert norm == 'a "b"'
    assert [text[i] for i in idx] == ["a", "　", "“", "b", "”"]


def test_fuzzy_find_needle_longer_than_text():
    assert fuzzy_find("Hi.", "Hi there, how are you doing tonight?") is None
    s, e = fuzzy_find("Hi Mia", "Hi Mia!")
    assert (s, e) == (0, 6)
