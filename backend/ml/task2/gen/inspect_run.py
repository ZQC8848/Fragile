"""Summarise a generation run: mix vs targets, teacher health, cost proxies, and requested-vs-judged violations.

    uv run python -m ml.task2.gen.inspect_run --run pilot
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from statistics import mean, median

from .run_selfplay import DATA_ROOT


def _pct(c: Counter, total: int) -> str:
    return ", ".join(f"{k}={v} ({v / total:.0%})" for k, v in c.most_common())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    d = DATA_ROOT / "raw" / args.run
    sessions = [json.loads(x) for x in (d / "sessions.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [json.loads(x) for x in (d / "turns.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()] if (d / "turns.jsonl").exists() else []
    print(f"run {args.run}: {len(sessions)} sessions, {len(rows)} records")
    print("session status:", dict(Counter(s["status"] for s in sessions)))
    print("endings:", dict(Counter(s["ending"] for s in sessions)))
    if sessions:
        print(f"latency per game: mean {mean(s['latency_s'] for s in sessions):.0f}s, median {median(s['latency_s'] for s in sessions):.0f}s")
        print(f"calls per game: player {mean(s['player_calls'] for s in sessions):.1f}, review {mean(s['review_calls'] for s in sessions):.1f}")
    for s in sessions:
        if s["status"] == "failed":
            print("  FAILED", s["session"], s["error"])
    if not rows:
        return
    first = [r for r in rows if r["attempt"] == 0]
    n = len(first)
    print("\nmix (player turns):")
    print("  persona:", _pct(Counter(r["persona"] for r in first), n))
    print("  lang:   ", _pct(Counter(r["lang"] for r in first), n), "   target en 80 / zh 10 / mix 10 (per game)")
    print("  mode requested:", _pct(Counter(r["mode"] for r in first), n), "   target single 80")
    print("  mode written:  ", _pct(Counter((r["input"] or {}).get("mode", "silence") for r in first), n))
    print("  violation requested:", sum(1 for r in first if r["violate_requested"]) / n, "  target 0.10")
    print("  outcome:", _pct(Counter(r["outcome"] for r in rows), len(rows)))
    teach = [r for r in rows if r["teacher"]]
    fb = sum(1 for r in teach if r["teacher"]["fallback"])
    retries = sum(r["teacher"]["retries"] for r in teach)
    print(f"\nteacher: {len(teach)} labelled, fallback kept={fb} (must be 0), retries={retries}")
    lat = [r["teacher"]["meta"].get("latency_ms", 0) for r in teach]
    if lat:
        print(f"  review latency: median {median(lat) / 1000:.1f}s, max {max(lat) / 1000:.1f}s")
    print(f"  model: {Counter(r['teacher']['meta'].get('model') for r in teach)}")
    cin = sum(r["review_chars_in"] for r in teach)
    cout = sum(r["review_chars_out"] for r in teach)
    pin = sum(s["player_chars_in"] for s in sessions)
    pout = sum(s["player_chars_out"] for s in sessions)
    print(f"  chars: review in {cin:,} / out {cout:,}; player in {pin:,} / out {pout:,}  (tokens ~ chars/4 English, chars/1.5 Chinese)")
    print("\nrequested violation vs teacher label:")
    pairs = Counter((r["violate_requested"], r["validity"]["label"]) for r in first if r["violate_requested"])
    for (req, got), c in pairs.most_common():
        print(f"  {req:13s} -> {got:13s} {c}")
    agree = sum(c for (req, got), c in pairs.items() if req == got)
    tot = sum(pairs.values())
    if tot:
        print(f"  agreement {agree}/{tot} = {agree / tot:.0%}")
    print("\nsample inputs:")
    for r in [x for x in first if x["input"]][:: max(1, n // 12)][:12]:
        inp = r["input"]
        text = inp.get("text") if inp["mode"] == "single" else inp["channels"]
        acts = [u["act"] for u in (r["teacher"] or {}).get("data", {}).get("units", [])] if r["teacher"] else None
        print(f"  [{r['lang']}/{inp['mode']}] {text}  -> {r['validity']['label']} {acts}")


if __name__ == "__main__":
    main()
