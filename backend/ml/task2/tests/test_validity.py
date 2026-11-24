"""Compliance (validity) targets and metrics: span lookup, false-reject / miss, threshold curve."""
from ml.task2.train.data import violation_span
from ml.task2.train.metrics import span_report, validity_binary_report


def _ex(text, label="ok", span=None):
    return {"text": text, "validity": {"label": label, "span": span, "message": None}}


def test_violation_span_found_and_quoted():
    assert violation_span(_ex("I smile. Julian laughs at my joke.", "npc_action", "Julian laughs at my joke.")) == (9, 34)
    # the teacher sometimes wraps the span in quotes the text does not have
    assert violation_span(_ex("Mia hands me the key.", "npc_action", "“Mia hands me the key.”")) == (0, 21)
    assert violation_span(_ex("hello", "ok")) is None
    assert violation_span(_ex("hello", "meta", "not in the text")) is None


def test_binary_report_counts_and_curve():
    y_true = ["ok", "ok", "ok", "ok", "meta", "invention"]
    y_pred = ["ok", "meta", "ok", "ok", "meta", "ok"]
    p_ok = [0.9, 0.3, 0.8, 0.95, 0.1, 0.6]
    r = validity_binary_report(y_true, y_pred, p_ok)
    assert r["false_reject"] == 0.25 and r["miss"] == 0.5
    assert r["category_acc_on_violations"] == 0.5
    at = {c["threshold"]: c for c in r["curve"]}
    assert at[0.5]["false_reject"] == 0.25 and at[0.5]["miss"] == 0.5
    assert 0.0 <= r["auroc"] <= 1.0


def test_span_report_char_f1():
    ex = _ex("I smile. Julian laughs.", "npc_action", "Julian laughs.")
    perfect = span_report([ex], [[[9, 23]]])
    assert perfect["char_f1"] == 1.0
    assert span_report([ex], [[]])["char_f1"] == 0.0
