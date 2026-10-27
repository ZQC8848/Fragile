"""The self-play round report (selfplay.md §8), computed from the logs alone, at no LLM cost.

    uv run python -m selfplay report r1            from the packs in data/selfplay/r1/
    uv run python -m selfplay report r1 --raw      from data/selfplay_raw/r1/ (before packing)

Sections: run (statuses, crash rate, turns, wall time, tokens, cost), personas vs behaviour (each axis
against the behaviour it should drive, plus agreeableness against accusations), collapse (distinct-n and
act entropy per player model), coverage and quality (endings, beats, generated beats, rejections, guard
rewrites, narrator fallbacks, latency).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

from selfplay.pack import PACKS_DIR, read_pack
from selfplay.run import RAW_DIR

CURIOUS_ACTS = {"ask", "ask_about_leo", "ask_about_crate", "ask_about_afternoon", "ask_about_move", "mention_car", "mention_voicemail"}
CURIOUS_VERBS = {"examine", "search", "listen_voicemail", "look_out", "knock", "open"}
CONFRONT_ACTS = {"disagree", "criticize", "provoke", "accuse_julian", "accuse_mia", "threaten_to_tell"}
CONFRONT_VERBS = {"grab", "push", "hit"}
ACCUSE_ACTS = {"accuse_julian", "accuse_mia"}
COMPLY_ACTS = {"agree", "thank", "praise"}


def _read_dir(d: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in d.iterdir():
        if f.suffix == ".jsonl":
            out[f.name] = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        elif f.suffix == ".json":
            out[f.name] = json.loads(f.read_text(encoding="utf-8"))
    return out


def load_round(round_name: str, *, raw: bool = False) -> list[dict[str, Any]]:
    if raw:
        dirs = sorted(p for p in (RAW_DIR / round_name).glob("*/*") if p.is_dir() and (p / "selfplay.json").exists())
        return [_read_dir(d) for d in dirs]
    return [read_pack(p) for p in sorted((PACKS_DIR / round_name).glob("*/*.tar.gz"))]


# ----------------------------------------------------------------------------------------------- per session
def player_turns(s: dict[str, Any]) -> list[dict[str, Any]]:
    """The turns the player played (turn 0 is the opening)."""
    return [t for t in s.get("turns.jsonl", []) if t.get("turn", 0) > 0]


def units(t: dict[str, Any]) -> list[dict[str, Any]]:
    return (t.get("understanding") or {}).get("units") or []


def behaviour(s: dict[str, Any]) -> dict[str, float]:
    turns = player_turns(s)
    n = max(len(turns), 1)
    acts = [u.get("act") for t in turns for u in units(t)]
    verbs = [((u.get("action") or {}).get("verb")) for t in turns for u in units(t)]
    speech = [(t.get("input") or {}).get("channels", {}).get("speech") or "" for t in turns]
    final = (turns[-1]["state"] if turns else {}) or {}
    return {
        "curiosity": (sum(a in CURIOUS_ACTS for a in acts) + sum(v in CURIOUS_VERBS for v in verbs)) / n,
        "confrontation": (sum(a in CONFRONT_ACTS for a in acts) + sum(v in CONFRONT_VERBS for v in verbs)) / n,
        "accusations": sum(a in ACCUSE_ACTS for a in acts) / n,
        "leave": (sum(a == "leave" for a in acts) + sum(v == "leave" for v in verbs)) / n,
        "compliance": sum(a in COMPLY_ACTS for a in acts) / n,
        "verbosity": mean(len(x.split()) for x in speech) if speech else 0.0,
        "honesty_to_nora": {"truth": 1.0, "none": 0.5, "lie": 0.0}.get(final.get("nora_told", "none"), 0.5),
        "side_strength": abs(float(final.get("side", 0))) / 2,
    }


def player_lines(s: dict[str, Any]) -> list[str]:
    out = []
    for t in player_turns(s):
        ch = (t.get("input") or {}).get("channels") or {}
        line = " ".join(ch.get(k) or "" for k in ("action", "speech", "expression")).strip()
        if line:
            out.append(line)
    return out


# ----------------------------------------------------------------------------------------------- statistics
def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)


def distinct(lines: list[str], n: int) -> float | None:
    grams = [tuple(w[i : i + n]) for w in (line.lower().split() for line in lines) for i in range(len(w) - n + 1)]
    return len(set(grams)) / len(grams) if grams else None


def entropy(items: list[Any]) -> float | None:
    c = Counter(items)
    total = sum(c.values())
    if not total:
        return None
    return -sum(v / total * math.log2(v / total) for v in c.values())


def _r(x: float | None, k: int = 3) -> float | None:
    return None if x is None else round(x, k)


# ----------------------------------------------------------------------------------------------- the report
def build(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    infos = [s.get("selfplay.json") or {} for s in sessions]
    played = [s for s, i in zip(sessions, infos, strict=True) if i.get("status") in ("ended", "max_turns")]
    statuses = Counter(i.get("status") for i in infos)
    run = {
        "sessions": len(sessions),
        "statuses": dict(statuses),
        "crash_rate": _r(statuses.get("error", 0) / len(sessions)) if sessions else None,
        "turns_median": median([i.get("turns", 0) for i in infos]) if infos else None,
        "wall_s_median": median([i.get("wall_s", 0) for i in infos]) if infos else None,
        "wall_s_total": round(sum(i.get("wall_s", 0) for i in infos), 1),
        "cost_usd_total": round(sum((i.get("usage") or {}).get("cost_usd", 0) for i in infos), 4),
        "cost_usd_per_session": _r(mean([(i.get("usage") or {}).get("cost_usd", 0) for i in infos]), 4) if infos else None,
        "tokens_per_session": round(mean([(i.get("usage") or {}).get("tokens", 0) for i in infos])) if infos else None,
        "by_model": _by_model(infos),
    }

    # personas vs behaviour
    rows = [(s["persona.json"]["persona"], behaviour(s)) for s in played if "persona.json" in s]
    axes = {}
    for axis in ("curiosity", "confrontation", "leave", "compliance", "verbosity", "honesty_to_nora", "side_strength"):
        axes[axis] = _r(pearson([p["axes_raw"][axis] for p, _ in rows], [b[axis] for _, b in rows]))
    hexaco = {
        "A vs accusations": _r(pearson([p["hexaco"]["A"] for p, _ in rows], [b["accusations"] for _, b in rows])),
        "X vs verbosity": _r(pearson([p["hexaco"]["X"] for p, _ in rows], [b["verbosity"] for _, b in rows])),
        "O vs curiosity": _r(pearson([p["hexaco"]["O"] for p, _ in rows], [b["curiosity"] for _, b in rows])),
        "H vs honesty_to_nora": _r(pearson([p["hexaco"]["H"] for p, _ in rows], [b["honesty_to_nora"] for _, b in rows])),
    }

    # collapse, per player model
    collapse = {}
    by_player: dict[str, list[dict[str, Any]]] = {}
    for s in played:
        by_player.setdefault((s.get("selfplay.json") or {}).get("player_profile", "?"), []).append(s)
    for name, group in sorted(by_player.items()):
        lines = [x for s in group for x in player_lines(s)]
        acts = [u.get("act") for s in group for t in player_turns(s) for u in units(t)]
        collapse[name] = {"sessions": len(group), "lines": len(lines), "distinct_1": _r(distinct(lines, 1)),
                          "distinct_2": _r(distinct(lines, 2)), "act_entropy_bits": _r(entropy(acts))}

    # coverage and quality
    endings = Counter((s.get("selfplay.json") or {}).get("ending") for s in played)
    beats = Counter(h["beat_id"] for s in played for h in (player_turns(s)[-1]["state"]["beat_history"] if player_turns(s) else [])
                    if h.get("completed"))
    turns = [t for s in played for t in player_turns(s)]
    attempts = sum(((s.get("selfplay.json") or {}).get("player") or {}).get("attempts", 0) for s in played)
    rejected = sum(((s.get("selfplay.json") or {}).get("player") or {}).get("rejected", 0) for s in played)
    coverage = {
        "endings": dict(endings.most_common()),
        "largest_ending_share": _r(max(endings.values()) / len(played)) if played else None,
        "beats_completed": dict(beats.most_common()),
        "generated_beats": sum(1 for t in turns if t.get("generated")),
        "rejection_rate": _r(rejected / attempts) if attempts else None,
        "guard_rewrite_rate": _r(mean([max(len(t.get("guard") or []) - 1, 0) > 0 for t in turns])) if turns else None,
        "narrator_fallback_rate": _r(mean([bool((t.get("narrator") or {}).get("fallback")) for t in turns])) if turns else None,
        "turn_latency_ms_median": median([(t.get("latency_ms") or {}).get("total", 0) for t in turns]) if turns else None,
    }
    return {"run": run, "axes_vs_behaviour": axes, "hexaco_vs_behaviour": hexaco, "collapse": collapse, "coverage": coverage}


def _by_model(infos: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    for i in infos:
        for model, row in ((i.get("usage") or {}).get("by_model") or {}).items():
            o = out.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
            for k in ("calls", "input_tokens", "output_tokens", "cost_usd"):
                o[k] += row.get(k, 0)
    for o in out.values():
        o["cost_usd"] = round(o["cost_usd"], 4)
    return out


def main_report(sessions: list[dict[str, Any]], as_json: bool = False) -> str:
    rep = build(sessions)
    if as_json:
        return json.dumps(rep, indent=1, ensure_ascii=False)
    lines = []
    for section, body in rep.items():
        lines.append(f"## {section}")
        for k, v in body.items():
            lines.append(f"  {k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, dict | list) else v}")
        lines.append("")
    lines.append("Axes near 0 mean the player models did not act on that axis (selfplay.md §8): revise its rules or drop it.")
    return "\n".join(lines)
