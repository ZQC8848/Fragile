"""uv run python -m selfplay <command>

    persona [--n 10] [--seed 1] [--render rules|numeric] [--json]   preview persona cards
    persona --stats [--n 2000] [--seed 1]                            distribution check (selfplay.md §3)
"""

from __future__ import annotations

import argparse
import json
import sys

from .persona import PersonaGenerator, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m selfplay")
    sub = ap.add_subparsers(dest="command", required=True)
    pp = sub.add_parser("persona", help="preview random player personas")
    pp.add_argument("--n", type=int, default=None)
    pp.add_argument("--seed", type=int, default=1)
    pp.add_argument("--render", choices=["rules", "numeric"], default="rules")
    pp.add_argument("--json", action="store_true", help="print the full persona records")
    pp.add_argument("--stats", action="store_true", help="print distribution statistics instead of cards")
    args = ap.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
