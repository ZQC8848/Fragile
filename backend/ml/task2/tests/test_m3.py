"""M3: the rule that composes guard verdicts from the three perceptions, span lookup, and the binary metrics."""
from ml.task2.train.m3_data import compose, context_text, find_span
from ml.task2.train.m3_metrics import auroc, average_precision, binary_report, score


def _ex(kind="narration", text="Julian smiles.", opening=False, ending=False, revealed=(), **labels):
    lab = {"facts": [], "overreach": False, "overreach_span": None, "contradiction": False, "contradiction_span": None, "note": None}
    lab.update(labels)
    return {"ex_id": "s:1:0", "turn_id": "s:1", "source": "selfplay", "kind": kind, "speaker": None, "text": text,
            "opening": opening, "ending": ending, "revealed": list(revealed), "labels": lab, "player_input": None,
            "scene": {"room": "kitchen", "present": [], "heard_by": {"leo_dead": ["mia"]}}, "previous_passage": "x" * 2000}


def test_compose_rules():
    assert compose(_ex(), ["leo_dead"], False, False) == "premature_leak"
    assert compose(_ex(revealed=["leo_dead"]), ["leo_dead"], False, False) == "consistent"
    assert compose(_ex(ending=True), ["leo_dead"], False, False) == "consistent"  # everything may come out
    assert compose(_ex(), ["leo_dead"], True, True) == "premature_leak"  # leak first, then contradiction
    assert compose(_ex(), [], True, True) == "contradiction"
    # Guard.failures: overreach does not count at the opening, nor in an ending outside my quoted speech
    assert compose(_ex(kind="me", opening=True), [], True, False) == "consistent"
    assert compose(_ex(kind="me", ending=True), [], True, False) == "consistent"
    assert compose(_ex(kind="me_speech", ending=True), [], True, False) == "player_overreach"
    assert compose(_ex(kind="me"), [], True, False) == "player_overreach"


def test_find_span_and_context():
    assert find_span("I smile. I take the key.", "I take the key.") == (9, 24)
    assert find_span("Mia nods.", "“Mia nods.”") == (0, 9)
    assert find_span("Mia nods.", "Julian") is None
    ctx = context_text(_ex())
    assert ctx.index("before:") < ctx.index("heard:")  # truncation drops the heard list first
    assert "x" * 701 not in ctx  # previous passage trimmed to its tail


def test_binary_metrics():
    y, s = [1, 0, 1, 0], [0.9, 0.8, 0.4, 0.1]
    assert auroc(y, s) == 0.75
    assert abs(average_precision(y, s) - (1 + 2 / 3) / 2) < 1e-9
    r = binary_report(y, s, 0.5)
    assert r["precision"] == 0.5 and r["recall"] == 0.5 and r["false_alarm"] == 0.5


def test_score_passage_level():
    a = _ex(kind="me", overreach=True, overreach_span=[0, 14])
    b = {**_ex(), "ex_id": "s:1:1"}
    m = score([a, b], [{"facts": [], "p_overreach": 0.9, "p_contradiction": 0.1, "overreach_span": [[0, 14]]},
                       {"facts": [], "p_overreach": 0.1, "p_contradiction": 0.1}])
    assert m["overreach"]["f1"] == 1.0 and m["overreach"]["span"]["char_f1"] == 1.0
    assert m["passage"]["n"] == 1 and m["passage"]["recall"] == 1.0
    assert m["verdict"]["false_alarm"] == 0.0
