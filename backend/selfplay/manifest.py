"""A round's manifest (selfplay.md §7, §7.1): every session's persona, player model, DM policy, split and
seed, fixed before anything runs, then cut into shards.

    selfplay/manifests/<round>/manifest.json    the whole round
    selfplay/manifests/<round>/shard-NN.json    one teammate's part: the same header, a slice of sessions

Stratified: sessions are ordered by stratum (tail or population x gender) and each assignment is spread
evenly along that order, so every stratum gets about the same mix of player models; DM policies are
spread within each player model, splits within each (model, policy). A round's personas come from a
seed derived from the round name, so two rounds never share a persona.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import date
from pathlib import Path
from typing import Any

from engine.llm import ROLES, prompt_versions

from .persona import PersonaGenerator
from .profiles import Profiles

MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"
SCHEMA_VERSION = 1


def round_seed(round_name: str) -> int:
    return int(hashlib.sha256(f"fragile-selfplay:{round_name}".encode()).hexdigest()[:8], 16)


def quotas(n: int, shares: dict[str, float]) -> dict[str, int]:
    """Largest-remainder rounding of n * share; the counts sum to n."""
    exact = {k: n * v for k, v in shares.items()}
    out = {k: int(v) for k, v in exact.items()}
    for k in sorted(exact, key=lambda k: (-(exact[k] - out[k]), list(shares).index(k)))[: n - sum(out.values())]:
        out[k] += 1
    return out


def spread(counts: dict[str, int]) -> list[str]:
    """The labels laid out evenly: label k's j-th copy sits at (j + 0.5) / count_k along the line."""
    marks = [((j + 0.5) / c, i, k) for i, (k, c) in enumerate(counts.items()) for j in range(c)]
    return [k for _, _, k in sorted(marks)]


def current_prompt_versions() -> dict[str, int]:
    return {role: max(v) for role in ROLES if (v := prompt_versions(role))}


def stratum(persona: dict[str, Any]) -> tuple[str, str]:
    return ("tail" if persona["sampling"]["tail"] else "population", persona["identity"]["gender"])


def build(round_name: str, n: int, *, subscription: int = 0, seed: int | None = None, profiles: Profiles | None = None,
          splits: dict[str, float] | None = None) -> dict[str, Any]:
    """n API sessions plus `subscription` sessions per subscription model."""
    prof = profiles or Profiles()
    gen = PersonaGenerator()
    seed = round_seed(round_name) if seed is None else seed
    rng = random.Random(seed)
    test_only = set(prof.players.get("test_only") or [])
    subs = list(prof.players.get("subscription") or []) if subscription else []
    total = n + subscription * len(subs)
    personas = [gen.generate_one(seed, i).to_json() for i in range(total)]

    # player models: API sessions spread over the strata, subscription sessions likewise
    order = sorted(range(total), key=lambda i: (stratum(personas[i]), rng.random()))
    api_idx = order[:]
    sub_idx: list[int] = []
    if subs:
        m = subscription * len(subs)
        sub_marks = {order[int((j + 0.5) * total / m)] for j in range(m)}
        while len(sub_marks) < m:  # collisions on tiny rounds
            sub_marks.add(next(i for i in order if i not in sub_marks))
        sub_idx = [i for i in order if i in sub_marks]
        api_idx = [i for i in order if i not in sub_marks]
    player: dict[int, str] = {}
    for i, label in zip(api_idx, spread(quotas(len(api_idx), prof.player_shares())), strict=True):
        player[i] = label
    for i, label in zip(sub_idx, spread({s: subscription for s in subs}), strict=True):
        player[i] = label

    # DM policy within each player model, along the stratum order
    dm_shares = {d["policy"]: float(d["share"]) for d in prof.dm}
    dm_of = {d["policy"]: d for d in prof.dm}
    policy: dict[int, str] = {}
    for model in dict.fromkeys(player[i] for i in order):
        members = [i for i in order if player[i] == model]
        for i, label in zip(members, spread(quotas(len(members), dm_shares)), strict=True):
            policy[i] = label

    # splits within each (model, policy)
    split_shares = splits or prof.splits
    split: dict[int, str] = {}
    for key in dict.fromkeys((player[i], policy[i]) for i in order):
        members = [i for i in order if (player[i], policy[i]) == key]
        if key[0] in test_only:
            split.update(dict.fromkeys(members, "test"))
            continue
        for i, label in zip(members, spread(quotas(len(members), split_shares)), strict=True):
            split[i] = label

    sessions = []
    for i, p in enumerate(personas):
        d = dm_of[policy[i]]
        sessions.append({
            "id": f"{round_name}-{i:04d}",
            "index": i,
            "split": split[i],
            "player_profile": player[i],
            "dm": {"policy": d["policy"], "scorer": d["scorer"], "tau": float(d.get("tau", 1.0))},
            "seed": int(hashlib.sha256(f"{seed}:{i}".encode()).hexdigest()[:8], 16),
            "persona": p,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "round": round_name,
        "tag": f"selfplay-{round_name}",
        "created": date.today().isoformat(),
        "persona_seed": seed,
        "generator_version": gen.cfg["generator_version"],
        "prompt_versions": current_prompt_versions(),
        "profiles_hash": prof.hash,
        "engine_roles": {r: prof[name].model or name for r, name in prof.engine_roles.items()},
        "n": total,
        "sessions": sessions,
    }


def shard(manifest: dict[str, Any], k: int) -> list[dict[str, Any]]:
    """k shards: sessions dealt round-robin in (player model, index) order, so each shard gets about the same
    number of every player model, the subscription ones included."""
    ordered = sorted(manifest["sessions"], key=lambda s: (s["player_profile"], s["index"]))
    head = {key: v for key, v in manifest.items() if key != "sessions"}
    out = []
    for j in range(k):
        part = sorted(ordered[j::k], key=lambda s: s["index"])
        out.append({**head, "shard": f"shard-{j + 1:02d}", "shards": k, "sessions": part})
    return out


def write(manifest: dict[str, Any], shards: int, directory: Path | None = None) -> list[Path]:
    d = (directory or MANIFESTS_DIR) / manifest["round"]
    if d.exists() and any(d.iterdir()):
        raise FileExistsError(f"{d} already has a manifest; a round's manifest is never regenerated in place")
    d.mkdir(parents=True, exist_ok=True)
    paths = [d / "manifest.json"]
    paths[0].write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for part in shard(manifest, shards):
        path = d / f"{part['shard']}.json"
        path.write_text(json.dumps(part, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def load(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summary(manifest: dict[str, Any]) -> dict[str, Any]:
    """Counts per player model, DM policy, split and stratum: the balance check printed after generation."""
    def count(f) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in manifest["sessions"]:
            k = f(s)
            out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items()))

    return {
        "sessions": len(manifest["sessions"]),
        "player": count(lambda s: s["player_profile"]),
        "dm": count(lambda s: s["dm"]["policy"]),
        "split": count(lambda s: s["split"]),
        "stratum": count(lambda s: "/".join(stratum(s["persona"]))),
        "player x stratum": count(lambda s: f"{s['player_profile']} {'/'.join(stratum(s['persona']))}"),
    }
