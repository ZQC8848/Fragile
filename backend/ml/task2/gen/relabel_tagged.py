"""Segmentation labels on the original text: the teacher echoes each single-box input with channel tags.

The group's review output gives the three channels as translated, rewritten English, which cannot be
mapped back onto the player's original characters. This script asks the same teacher (role `review`,
our own system prompt, prompt_version 101) to repeat the input verbatim with
<S i=N>…</S> / <A>…</A> / <E>…</E> around its parts, numbering speech by the teacher's own speech units,
then aligns the tags onto the original (common/align.py).

Methods recorded per item:
  tagged   the echo matched the original and was aligned
  fuzzy    the echo failed; the teacher's channels were found in the original by fuzzy match (English only)
  trivial  channels-mode input: the segmentation is the channels themselves, no API call
  drop     nothing reliable

    uv run python -m ml.task2.gen.relabel_tagged --run pilot
    uv run python -m ml.task2.gen.relabel_tagged --run pilot --report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from engine.llm import load_env

from ..common.align import Span, align_tagged, assign_units, fuzzy_find
from .run_selfplay import DATA_ROOT

PROMPT_VERSION = 101
SYSTEM = """You segment ONE line of player input from a text adventure into channels. You never change the text.

Channels:
- S = speech: words said aloud (quoted text, or text that is plainly dialogue).
- A = action: movement, things done with objects or bodies.
- E = expression: face, tone, gaze, posture, feelings shown.

You also get the teacher's units: the speech sentences, action and expression it found, in English (they may be
translations). Use them to decide which part of the ORIGINAL text belongs to which channel, and number every
speech tag with the index of the speech unit it corresponds to (speech units are numbered 0, 1, 2… in the order given).

Reply with JSON {"tagged": "..."} where "tagged" is the ORIGINAL text repeated EXACTLY, character for character
(same language, same words, same punctuation, same quotation marks, no translation, no corrections), with tags
inserted: <S i=0>…</S>, <S i=1>…</S>, <A>…</A>, <E>…</E>. Tags never nest. Quotation marks may sit inside or outside
a speech tag. Text that belongs to no channel (connecting words, stray punctuation) stays outside all tags.

Example
input: 我盯着 Julian，问他："Leo 下午来过吗？"
units: [{"i":0,"channel":"speech","text":"Was Leo here this afternoon?"},{"channel":"action","text":"ask him"},{"channel":"expression","text":"I stare at Julian"}]
reply: {"tagged": "<E>我盯着 Julian</E>，<A>问他</A>：<S i=0>\\"Leo 下午来过吗？\\"</S>"}"""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["tagged"], "properties": {"tagged": {"type": "string"}}}


def rec_id(r: dict[str, Any]) -> str:
    return f"{r['session']}:{r['turn']}:{r['attempt']}"


def _units_for_prompt(units: list[dict]) -> list[dict]:
    out, k = [], 0
    for u in units:
        if u.get("act") == "silence":
            continue
        item = {"channel": u.get("channel"), "text": u.get("text") or ""}
        if u.get("channel") == "speech":
            item = {"i": k, **item}
            k += 1
        out.append(item)
    return out


def trivial_spans(channels: dict[str, Any]) -> tuple[str, list[Span]]:
    """Channels-mode input as one text '[S] … [A] … [E] …' with exact spans (no API call)."""
    text, spans = "", []
    for ch, tag in (("speech", "S"), ("action", "A"), ("expression", "E")):
        val = (channels.get(ch) or "").strip()
        if not val:
            continue
        if text:
            text += " "
        text += f"[{tag}] "
        spans.append(Span(ch, len(text), len(text) + len(val)))
        text += val
    return text, spans


def _result(r, method: str, text: str, spans: list[Span], units: list[dict], meta: dict | None = None, tagged: str | None = None) -> dict:
    placed, how = assign_units(text, spans, units) if spans else ([None] * len(units), "none")
    return {
        "id": rec_id(r), "session": r["session"], "lang": r["lang"], "mode": r["input"]["mode"], "method": method,
        "text": text, "segments": [s.as_dict() for s in spans], "unit_spans": [list(p) if p else None for p in placed],
        "unit_method": how, "tagged": tagged, "meta": meta,
    }


async def relabel_one(client, sem, r: dict[str, Any]) -> dict[str, Any]:
    units = r["teacher"]["data"].get("units") or []
    if r["input"]["mode"] == "channels":
        text, spans = trivial_spans(r["input"]["channels"])
        return _result(r, "trivial", text, spans, units)
    original = r["input"]["text"]
    user = "Segment this input. Return only the JSON object.\n\n" + json.dumps(
        {"input": original, "units": _units_for_prompt(units)}, ensure_ascii=False, indent=1)
    tagged, meta = None, None
    async with sem:
        try:
            res = await client.call_json(SYSTEM, user, schema=SCHEMA, prompt_version=PROMPT_VERSION)
            tagged, meta = res.data["tagged"], res.meta()
        except Exception as e:  # provider error: fall through to fuzzy / drop
            meta = {"error": f"{type(e).__name__}: {e}"}
    spans = align_tagged(original, tagged) if tagged else None
    if spans:
        return _result(r, "tagged", original, spans, units, meta, tagged)
    if not r["teacher"]["data"].get("translated"):
        ch = r["teacher"]["data"].get("channels") or {}
        found = []
        for name in ("speech", "action", "expression"):
            if ch.get(name):
                hit = fuzzy_find(original, ch[name])
                if hit is None:
                    found = None
                    break
                found.append(Span(name, *hit))
        if found:
            found.sort(key=lambda s: s.start)
            if all(b.start >= a.end for a, b in zip(found, found[1:])):
                return _result(r, "fuzzy", original, found, units, meta, tagged)
    return _result(r, "drop", original, [], units, meta, tagged)


def report(path: Path) -> None:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    by = defaultdict(Counter)
    for x in rows:
        by[(x["mode"], x["lang"])][x["method"]] += 1
    print(f"{len(rows)} items")
    for (mode, lang), c in sorted(by.items()):
        tot = sum(c.values())
        print(f"  {mode:8s} {lang:4s} n={tot:4d}  " + "  ".join(f"{k}={v} ({v / tot:.0%})" for k, v in c.most_common()))
    um = Counter(x["unit_method"] for x in rows if x["method"] != "drop")
    print("unit placement:", dict(um))
    fails = [x for x in rows if x["mode"] == "single" and x["method"] != "tagged"][:20]
    if fails:
        print("\nfailures (first 20):")
        for x in fails:
            print(f"  [{x['lang']}] {x['method']}: {x['text']!r}\n      tagged={x['tagged']!r}")


async def run(args) -> None:
    from engine.llm import get_client

    src = DATA_ROOT / "raw" / args.run / "turns.jsonl"
    out = DATA_ROOT / "relabel" / f"{args.run}.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(x)["id"] for x in out.read_text(encoding="utf-8").splitlines() if x.strip()}
    rows = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    todo = [r for r in rows if r["teacher"] and r["input"] and rec_id(r) not in done]
    if args.limit:
        todo = todo[: args.limit]
    client = get_client("review", 0.0)
    sem = asyncio.Semaphore(args.slots)
    print(f"{len(todo)} to relabel ({len(done)} done)")
    lock = asyncio.Lock()

    async def one(r):
        res = await relabel_one(client, sem, r)
        async with lock:
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")

    await asyncio.gather(*(one(r) for r in todo))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--slots", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    (DATA_ROOT / "relabel").mkdir(parents=True, exist_ok=True)
    if args.report:
        report(DATA_ROOT / "relabel" / f"{args.run}.jsonl")
        return
    load_env()
    os.environ["LLM_LIVE_ROLES"] = "review"
    os.environ["LLM_CACHE"] = "0"
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
