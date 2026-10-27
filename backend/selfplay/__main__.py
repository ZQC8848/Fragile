"""uv run python -m selfplay <command>   (selfplay.md §7, §7.1)

    doctor [--probe]                                        can this machine run self-play, which sessions
    manifest --round r1 --n 30 [--shards 6] [--subscription 0] [--split train=.7,dev=.15,test=.15]
                                                            write selfplay/manifests/<round>/ (once per round)
    run --shard selfplay/manifests/r1/shard-03.json [--budget-usd 5] [--concurrency 6] [--max-sessions N]
        [--max-turns 60] [--max-tokens N] [--retry-errors] [--session ID ...] [--no-cache] [--allow-dirty]
                                                            play the shard; run again to resume
    pack --shard selfplay/manifests/r1/shard-03.json        finished sessions -> data/selfplay/<round>/<shard>/
    check r1 [--complete]                                   validate a round's packs against its manifest
    report r1 [--raw] [--json]                              the round's report (tools/selfplay_report.py)
    persona [--n 10] [--seed 1] [--render rules|numeric] [--json]   preview persona cards
    persona --stats [--n 2000] [--seed 1]                            distribution check (selfplay.md §3)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .persona import PersonaGenerator, stats


def _split(raw: str | None) -> dict[str, float] | None:
    if not raw:
        return None
    return {k.strip(): float(v) for k, v in (item.split("=") for item in raw.split(","))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m selfplay")
    sub = ap.add_subparsers(dest="command", required=True)
    pp = sub.add_parser("persona", help="preview random player personas")
    pp.add_argument("--n", type=int, default=None)
    pp.add_argument("--seed", type=int, default=1)
    pp.add_argument("--render", choices=["rules", "numeric"], default="rules")
    pp.add_argument("--json", action="store_true", help="print the full persona records")
    pp.add_argument("--stats", action="store_true", help="print distribution statistics instead of cards")

    dp = sub.add_parser("doctor", help="check keys, endpoints and the claude / codex command lines")
    dp.add_argument("--probe", action="store_true", help="also ask claude and codex for one tiny answer")

    mp = sub.add_parser("manifest", help="generate a round's manifest and shards")
    mp.add_argument("--round", required=True)
    mp.add_argument("--n", type=int, required=True, help="API-model sessions")
    mp.add_argument("--shards", type=int, default=6)
    mp.add_argument("--subscription", type=int, default=0, help="extra sessions per subscription model (claude, gpt)")
    mp.add_argument("--seed", type=int, default=None, help="persona seed (default: derived from the round name)")
    mp.add_argument("--split", default=None, help="e.g. train=0.7,dev=0.15,test=0.15")
    mp.add_argument("--dry-run", action="store_true", help="print the balance without writing files")

    rp = sub.add_parser("run", help="play a shard's sessions (resumable)")
    rp.add_argument("--shard", required=True, type=Path)
    rp.add_argument("--budget-usd", type=float, default=None)
    rp.add_argument("--max-tokens", type=int, default=None)
    rp.add_argument("--max-sessions", type=int, default=None)
    rp.add_argument("--max-turns", type=int, default=None)
    rp.add_argument("--concurrency", type=int, default=None)
    rp.add_argument("--retry-errors", action="store_true")
    rp.add_argument("--session", action="append", default=None, help="play only this session id (repeatable)")
    rp.add_argument("--no-cache", action="store_true", help="do not read or write the LLM response cache")
    rp.add_argument("--allow-dirty", action="store_true", help="run on uncommitted changes (check rejects those sessions)")

    kp = sub.add_parser("pack", help="pack a shard's finished sessions into data/selfplay/")
    kp.add_argument("--shard", required=True, type=Path)

    cp = sub.add_parser("check", help="validate a round's packs")
    cp.add_argument("round")
    cp.add_argument("--complete", action="store_true", help="missing sessions are an error")

    rep = sub.add_parser("report", help="the round's report: personas vs behaviour, collapse, coverage, cost")
    rep.add_argument("round")
    rep.add_argument("--raw", action="store_true", help="read data/selfplay_raw/ instead of the packs")
    rep.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.command != "persona":
        return _command(args)

    gen = PersonaGenerator()
    if args.stats:
        print(json.dumps(stats(gen, gen.generate(args.n or 2000, args.seed)), indent=2, ensure_ascii=False))
        return 0
    for p in gen.generate(args.n or 5, args.seed, args.render):
        if args.json:
            print(json.dumps(p.to_json(), ensure_ascii=False))
            continue
        tail = ", ".join(f"{d} {s}" for d, s in p.sampling["tail"]) or "population"
        print(f"#{p.index}  {p.identity['name']} ({p.identity['gender']})  {tail}  weight {p.sampling['weight']}")
        print("   " + "  ".join(f"{d} {v:+.2f}" for d, v in p.hexaco.items()))
        print("   " + "  ".join(f"{k} {v:.2f}" for k, v in p.axes.items()))
        for line in p.card:
            print(f"   - {line}")
        for name, lines in p.triggered.items():
            for line in lines:
                print(f"   [after {name}] {line}")
        print()
    return 0


def _command(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        from . import doctor

        result = doctor.check(probe=args.probe)
        print(doctor.report(result))
        return 0 if result["engine_ok"] else 1
    if args.command == "manifest":
        from . import manifest

        m = manifest.build(args.round, args.n, subscription=args.subscription, seed=args.seed, splits=_split(args.split))
        print(json.dumps(manifest.summary(m), indent=1))
        if not args.dry_run:
            for path in manifest.write(m, args.shards):
                print(f"wrote {path}")
            print(f"next: commit selfplay/manifests/{args.round}/ and tag it: git tag {m['tag']}")
        return 0
    if args.command == "run":
        from .manifest import load
        from .run import git_info, run_shard

        if git_info()["dirty"] and not args.allow_dirty:
            print("The working tree has uncommitted changes; `check` would reject these sessions. "
                  "Commit or stash them, or pass --allow-dirty for a local test.", file=sys.stderr)
            return 2
        result = asyncio.run(run_shard(
            load(args.shard), concurrency=args.concurrency, budget_usd=args.budget_usd, max_tokens=args.max_tokens,
            max_sessions=args.max_sessions, max_turns=args.max_turns, retry_errors=args.retry_errors,
            only=set(args.session) if args.session else None, cache=not args.no_cache,
        ))
        print(json.dumps(result, indent=1))
        return 0
    if args.command == "pack":
        from .manifest import load
        from .pack import pack_shard

        print(json.dumps(pack_shard(load(args.shard)), indent=1))
        return 0
    if args.command == "check":
        from .pack import check_round

        result = check_round(args.round, complete=args.complete)
        print(json.dumps(result, indent=1))
        return 0 if result["ok"] else 1
    if args.command == "report":
        from tools.selfplay_report import load_round, main_report

        sessions = load_round(args.round, raw=args.raw)
        print(main_report(sessions, as_json=args.json))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
