"""Run the prompt eval sets (prompts/evals/<role>.jsonl) and report accuracy (plan.md M4).

    uv run python tools/eval_prompts.py                    # all four sets, live LLM (keys from backend/.env)
    uv run python tools/eval_prompts.py --roles review     # one set
    uv run python tools/eval_prompts.py --offline          # the offline mocks: no network, no cost

Each set runs through the same code path the game uses (the llm path of each module), and the rule path runs
alongside as the baseline. Results go to prompts/evals/results/<role>.json (every item, with the model's
output) and a summary table to prompts/evals/results/summary.md, stamped with the model and prompt version:
the regression baseline for prompt changes.

These sets are for prompt regression only. The human-labelled test sets of backend-design.md §5.3 never tune
prompts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.llm import load_env  # noqa: E402

EVALS = Path(__file__).resolve().parents[1] / "prompts" / "evals"
ROLES = ("review", "guard", "tension", "scorer")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def pct(x: float) -> str:
    return f"{100 * x:.0f}%"


async def gather_limited(n: int, coros):
    sem = asyncio.Semaphore(n)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros))


# --------------------------------------------------------------------------- review (M2)
def score_review(item: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    exp = item["expect"]
    want = exp["validity"] if isinstance(exp["validity"], list) else [exp["validity"]]
    got = (out.get("validity") or {}).get("label")
    checks: dict[str, bool] = {"validity": got in want}
    units = out.get("units") or []
    ch = out.get("channels") or {}
    if "addressee" in exp:
        checks["addressee"] = ch.get("addressee") == exp["addressee"]
    if "acts" in exp:
        checks["acts"] = bool({u.get("act") for u in units} & set(exp["acts"]))
    if "action" in exp:
        acts = [u.get("action") for u in units if u.get("action")]
        checks["action"] = bool(acts) and (acts[0]["verb"], acts[0]["target"]) == (exp["action"]["verb"], exp["action"]["target"])
    if "translated" in exp:
        checks["translated"] = bool(out.get("translated")) == exp["translated"]
    if "nora_answer" in exp:
        checks["nora_answer"] = out.get("nora_answer") == exp["nora_answer"]
    if "claims" in exp:
        checks["claims"] = set(exp["claims"]) <= set(out.get("claims") or []) and bool(exp["claims"] or not out.get("claims"))
    if "speech_has" in exp:
        checks["speech"] = exp["speech_has"].lower() in (ch.get("speech") or "").lower()
    if got != "ok" and got in want and got not in ("absurd", "out_of_scope", "meta"):
        checks["rewrite"] = bool(out.get("rewrite"))
    return {"expected": want, "got": got, "checks": checks}


def summarize_review(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok_items = [r for r in rows if r["expected"] == ["ok"]]
    bad_items = [r for r in rows if "ok" not in r["expected"]]
    fields: dict[str, list[bool]] = {}
    for r in rows:
        for k, v in r["checks"].items():
            fields.setdefault(k, []).append(v)
    return {
        "n": len(rows),
        "validity_accuracy": sum(r["checks"]["validity"] for r in rows) / len(rows),
        "false_reject_rate": sum(r["got"] != "ok" for r in ok_items) / max(1, len(ok_items)),
        "miss_rate": sum(r["got"] == "ok" for r in bad_items) / max(1, len(bad_items)),
        "fields": {k: f"{sum(v)}/{len(v)}" for k, v in fields.items() if k != "validity"},
    }


async def eval_review(items, offline: bool, conc: int) -> dict[str, Any]:
    from engine.models.encoder import LLMEncoderPath
    from engine.models.rule_encoder import RuleEncoder
    from engine.state import StateSchema
    from engine.world import WorldRules

    world = WorldRules.from_file(StateSchema())
    rule = RuleEncoder(world.object_topics())
    llm = LLMEncoderPath(rule, action_table=world.action_table())
    outs = await gather_limited(conc, [llm.encode(i["input"], i["context"]) for i in items])
    res = {"llm": [], "rule": []}
    for item, out in zip(items, outs, strict=True):
        res["llm"].append({"id": item["id"], **score_review(item, out.data), "fallback": out.fallback, "meta": out.meta, "output": out.data})
        r = rule.encode(item["input"], item["context"])
        res["rule"].append({"id": item["id"], **score_review(item, r)})
    return {"items": res, "summary": {p: summarize_review(v) for p, v in res.items()}}


# --------------------------------------------------------------------------- guard (M3)
def summarize_guard(rows: list[dict[str, Any]]) -> dict[str, Any]:
    labels = sorted({r["expected"] for r in rows})
    recall = {}
    for lab in labels:
        sub = [r for r in rows if r["expected"] == lab]
        recall[lab] = f"{sum(r['got'] == lab for r in sub)}/{len(sub)}"
    clean = [r for r in rows if r["expected"] == "consistent"]
    return {
        "n": len(rows),
        "accuracy": sum(r["got"] == r["expected"] for r in rows) / len(rows),
        "detection": sum((r["got"] != "consistent") == (r["expected"] != "consistent") for r in rows) / len(rows),
        "false_block_rate": sum(r["got"] != "consistent" for r in clean) / max(1, len(clean)),
        "recall": recall,
    }


async def eval_guard(items, offline: bool, conc: int) -> dict[str, Any]:
    from engine.models.guard import GuardContext, LLMGuardPath, rule_verdicts

    llm = LLMGuardPath()

    def ctx(i):
        return GuardContext(allowed=set(i["allowed_facts"]), speaker_allowed={k: set(v) for k, v in i["speaker_allowed"].items()},
                            player=i["player_input"], ending=i["ending"], scene=i.get("scene") or {})

    outs = await gather_limited(conc, [llm.check(i["segments"], ctx(i)) for i in items])
    res = {"llm": [], "rule": []}
    for item, out in zip(items, outs, strict=True):
        v = out["verdicts"][0]
        res["llm"].append({"id": item["id"], "expected": item["expect"][0], "got": v["label"], "verdict": v, "meta": out["meta"], "fallback": out["fallback"]})
        rv = rule_verdicts(item["segments"], ctx(item))[0]
        res["rule"].append({"id": item["id"], "expected": item["expect"][0], "got": rv["label"]})
    return {"items": res, "summary": {p: summarize_guard(v) for p, v in res.items()}}


# --------------------------------------------------------------------------- tension (M4)
def spearman(a: list[float], b: list[float]) -> float:
    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r

    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = sum((x - ma) ** 2 for x in ra) ** 0.5
    vb = sum((y - mb) ** 2 for y in rb) ** 0.5
    return cov / (va * vb) if va and vb else 0.0


async def eval_tension(items, offline: bool, conc: int) -> dict[str, Any]:
    from engine.models.tension import LLMTensionPath

    llm = LLMTensionPath()
    outs = await gather_limited(conc, [llm.estimate(i["window"], {"tension": i["expect"] if offline else 1.0}) for i in items])
    rows = [{"id": i["id"], "expected": i["expect"], "got": float(o["tension"]), "reason": o.get("reason"), "meta": o["meta"]} for i, o in zip(items, outs, strict=True)]
    errs = [abs(r["got"] - r["expected"]) for r in rows]
    summary = {
        "n": len(rows),
        "mae": sum(errs) / len(errs),
        "within_1": sum(e <= 1 for e in errs) / len(errs),
        "spearman": spearman([r["expected"] for r in rows], [r["got"] for r in rows]),
    }
    return {"items": {"llm": rows}, "summary": {"llm": summary}}


# --------------------------------------------------------------------------- scorer (M1)
async def eval_scorer(items, offline: bool, conc: int) -> dict[str, Any]:
    from engine.beats import BeatPool, rule_ctx
    from engine.clock import StoryClock
    from engine.dm import DramaManager, TensionArc
    from engine.models.scorer import Candidate, ScoringContext
    from engine.paths import DATA_DIR
    from engine.state import StateSchema

    schema = StateSchema()
    clock = StoryClock.from_file()
    pool = BeatPool.from_dir(DATA_DIR / "beats", set(schema.props))
    dm = DramaManager(pool, TensionArc.from_file(), clock, scorer="llm", tau=0.01, seed=0)

    def build(item):
        state = schema.refresh_derived({**schema.initial_state(), **item["state"]})
        turn = {"acts": [], "topics": [], "claims": [], "action": None, "addressee": None, **item["turn"]}
        ctx = rule_ctx(state, turn)
        tension = float(state["tension"])
        cands = []
        for cid in item["candidates"]:
            if cid == "GENERATE_NEW":
                cands.append(Candidate(beat=None))
                continue
            b = pool.by_id[cid]
            entry = pool.entry_for(b, ctx) or b.entries[0]
            target = dm.arc.target_delta(state["story_min"], clock.minutes_for(b.minutes, state["story_min"]), tension) / 0.5
            cands.append(Candidate(beat=b, priority=pool.priority(b, ctx, entry), entry=entry, target_slope=target))
        sctx = ScoringContext(state, schema.textualize(state), 0, tension, item["recent_dialogue"], {"turn": turn})
        return sctx, cands

    async def one(item):
        sctx, cands = build(item)
        out = {}
        for path in ("llm", "rule"):
            res = await dm.scorers[path].score(sctx, cands)
            best = max(res, key=lambda r: r.score)
            out[path] = {"id": item["id"], "expected": item["expect"], "got": best.candidate_id, "hit": best.candidate_id in item["expect"],
                         "scores": {r.candidate_id: round(r.score, 3) for r in res}, "reasons": {r.candidate_id: r.reason for r in res}}
        out["meta"] = dm.scorers["llm"].last_meta
        return out

    outs = await gather_limited(conc, [one(i) for i in items])
    res = {p: [o[p] | ({"meta": o["meta"]} if p == "llm" else {}) for o in outs] for p in ("llm", "rule")}
    return {"items": res, "summary": {p: {"n": len(v), "top1": sum(r["hit"] for r in v) / len(v)} for p, v in res.items()}}


# --------------------------------------------------------------------------- main
RUNNERS = {"review": eval_review, "guard": eval_guard, "tension": eval_tension, "scorer": eval_scorer}


def model_stamp(role: str) -> dict[str, Any]:
    from engine.llm.client import _clients
    from engine.models.prompts import system_prompt

    c = _clients.get(role)
    return {
        "provider": c.config.effective_provider if c else None,
        "model": (c.config.model if c and c.config.effective_provider != "mock" else "mock"),
        "prompt_version": system_prompt(role).version,
    }


def summary_lines(role: str, stamp: dict[str, Any], summary: dict[str, Any], seconds: float) -> list[str]:
    head = f"### {role} · {stamp['model']} · prompt v{stamp['prompt_version']} · {seconds:.0f}s"
    lines = [head, ""]
    for path, s in summary.items():
        parts = []
        for k, v in s.items():
            parts.append(f"{k}={pct(v) if isinstance(v, float) and k not in ('mae', 'spearman') else (f'{v:.2f}' if isinstance(v, float) else v)}")
        lines.append(f"- **{path}**: " + ", ".join(parts))
    return lines + [""]


async def main_async(roles: list[str], offline: bool, conc: int, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    md = [f"# Prompt eval results · {time.strftime('%Y-%m-%d %H:%M')} · {'offline mocks' if offline else 'live'}", ""]
    for role in roles:
        items = read_jsonl(EVALS / f"{role}.jsonl")
        t0 = time.perf_counter()
        result = await RUNNERS[role](items, offline, conc)
        secs = time.perf_counter() - t0
        stamp = model_stamp(role)
        (out_dir / f"{role}.json").write_text(json.dumps({"stamp": stamp, **result}, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        lines = summary_lines(role, stamp, result["summary"], secs)
        print("\n".join(lines))
        md += lines
        failures = [r for r in result["items"]["llm"] if not (r.get("hit") if "hit" in r else (r.get("got") in (r["expected"] if isinstance(r["expected"], list) else [r["expected"]]) if role != "tension" else abs(r["got"] - r["expected"]) <= 1))]
        if failures:
            md.append("Misses (llm): " + ", ".join(f"`{r['id']}` ({r.get('got')})" for r in failures))
            md.append("")
    (out_dir / "summary.md").write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the prompt eval sets.")
    ap.add_argument("--roles", default=",".join(ROLES))
    ap.add_argument("--offline", action="store_true", help="answer from the offline mocks")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--out", default=str(EVALS / "results"))
    args = ap.parse_args()
    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    load_env()
    os.environ["LLM_LIVE_ROLES"] = "" if args.offline else ",".join(roles)
    asyncio.run(main_async(roles, args.offline, args.concurrency, Path(args.out)))


if __name__ == "__main__":
    main()
