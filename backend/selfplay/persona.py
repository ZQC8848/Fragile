"""Random player personas for self-play (selfplay.md §3 to §5).

    sample   a HEXACO vector: 70% from the population (multivariate normal with the configured
             intercorrelations), 30% from a tail (one or two domains forced into their top or bottom 15%,
             drawn by rejection from the same population, so the correlations survive). Every persona
             carries an importance weight back to the population.
    derive   behaviour axes (curiosity, confrontation, ...) as noisy weighted sums of the domains,
             squashed to 0..1; a side to lean toward; a goal; what to do if the truth comes out; style.
    render   what the player model is told: a few adjectives, three or four concrete rules, the goal.
             The numbers never reach the player, except in the numeric render kept for the A/B check.
             Nothing on the opening card hints at what happens tonight; a line that only makes sense once
             something has happened (what to do now that the truth is out) is held back as a TRIGGERED
             line and joins the card when its condition holds (`card_at`).

Deterministic: the same seed and index always give the same persona. Pure standard library.
"""

from __future__ import annotations

import itertools
import math
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import NormalDist
from typing import Any

import yaml

from engine.dsl import compile_expr, truthy

HERE = Path(__file__).resolve().parent
N01 = NormalDist()
#: wording used when no domain is far enough from the mean to give an adjective
PLAIN = ["even-tempered", "ordinary", "easy-going"]


def _load(name: str) -> Any:
    return yaml.safe_load((HERE / name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- small linear algebra
def _cholesky(m: list[list[float]]) -> list[list[float]]:
    n = len(m)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = m[i][j] - sum(out[i][k] * out[j][k] for k in range(j))
            if i == j:
                if s <= 0:
                    raise ValueError("the correlation matrix is not positive definite")
                out[i][j] = math.sqrt(s)
            else:
                out[i][j] = s / out[j][j]
    return out


def _both_above(c: float, r: float, steps: int = 4000) -> float:
    """P(Y1 > c, Y2 > c) for a standard bivariate normal with correlation r (Simpson's rule)."""
    if abs(r) < 1e-12:
        return (1 - N01.cdf(c)) ** 2
    hi = 8.0
    h = (hi - c) / steps
    s = math.sqrt(1 - r * r)

    def f(y: float) -> float:
        return N01.pdf(y) * (1 - N01.cdf((c - r * y) / s))

    total = f(c) + f(hi) + sum((4 if k % 2 else 2) * f(c + k * h) for k in range(1, steps))
    return total * h / 3


# --------------------------------------------------------------------------- the persona
@dataclass
class Persona:
    generator_version: int
    seed: int
    index: int
    sampling: dict[str, Any]
    hexaco: dict[str, float]
    axes: dict[str, float]
    axes_raw: dict[str, float]
    side: str
    goal: str
    stance: str
    style: dict[str, Any]
    identity: dict[str, str]
    #: what the player is told from the first turn
    card: list[str] = field(default_factory=list)
    #: trigger name -> lines added once it fires (selfplay.md §3.4)
    triggered: dict[str, list[str]] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class PersonaGenerator:
    def __init__(self, config: dict[str, Any] | None = None, rules: dict[str, Any] | None = None, goals: list[dict[str, Any]] | None = None):
        self.cfg = config or _load("persona_config.yaml")
        self.rules = rules or _load("persona_rules.yaml")
        self.goals = goals or _load("goals.yaml")
        self.dims: list[str] = self.cfg["dims"]
        n = len(self.dims)
        self.corr = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        for pair, r in (self.cfg.get("correlations") or {}).items():
            a, b = pair.split("-")
            i, j = self.dims.index(a), self.dims.index(b)
            self.corr[i][j] = self.corr[j][i] = float(r)
        self.chol = _cholesky(self.corr)
        self.triggers = {name: compile_expr(rule) for name, rule in (self.cfg.get("triggers") or {}).items()}

        tail = self.cfg["tail"]
        self.tail_fraction = float(tail["fraction"])
        self.cut = N01.inv_cdf(1 - float(tail["quantile"]))
        two = float(tail["two_dim_share"])
        singles = [((d,), (s,)) for d in range(n) for s in (1, -1)]
        doubles = [((a, b), (sa, sb)) for a, b in itertools.combinations(range(n), 2) for sa in (1, -1) for sb in (1, -1)]
        #: (dims, signs, probability of picking it, probability of the population landing in it)
        self.components: list[tuple[tuple[int, ...], tuple[int, ...], float, float]] = []
        for dims, signs in singles:
            self.components.append((dims, signs, (1 - two) / len(singles), float(tail["quantile"])))
        for (a, b), (sa, sb) in doubles:
            p = _both_above(self.cut, sa * sb * self.corr[a][b])
            self.components.append(((a, b), (sa, sb), two / len(doubles), p))

    # -- sampling ---------------------------------------------------------------------------
    def _population(self, rng: random.Random) -> list[float]:
        z = [rng.gauss(0, 1) for _ in self.dims]
        return [sum(self.chol[i][k] * z[k] for k in range(i + 1)) for i in range(len(self.dims))]

    def _inside(self, x: list[float], dims: tuple[int, ...], signs: tuple[int, ...]) -> bool:
        return all(s * x[d] > self.cut for d, s in zip(dims, signs, strict=True))

    def weight(self, x: list[float]) -> float:
        """Importance weight back to the population: population density over sampling density."""
        tail = sum(pick / pop for dims, signs, pick, pop in self.components if self._inside(x, dims, signs))
        return 1 / ((1 - self.tail_fraction) + self.tail_fraction * tail)

    def sample_traits(self, rng: random.Random) -> tuple[list[float], list[list[str]]]:
        if rng.random() >= self.tail_fraction:
            return self._population(rng), []
        dims, signs, _, _ = rng.choices(self.components, weights=[c[2] for c in self.components])[0]
        for _ in range(100_000):
            x = self._population(rng)
            if self._inside(x, dims, signs):
                return x, [[self.dims[d], "high" if s > 0 else "low"] for d, s in zip(dims, signs, strict=True)]
        raise RuntimeError("tail rejection sampling did not converge")

    # -- deriving ------------------------------------------------------------------------------
    def axes(self, x: list[float], rng: random.Random) -> tuple[dict[str, float], dict[str, float]]:
        sigma = float(self.cfg["noise_sd"])
        raw: dict[str, float] = {}
        scaled: dict[str, float] = {}
        for name, spec in self.cfg["axes"].items():
            w = [float(spec["weights"].get(d, 0.0)) for d in self.dims]
            lin = sum(wi * xi for wi, xi in zip(w, x, strict=True)) + rng.gauss(0, sigma)
            var = sum(w[i] * w[j] * self.corr[i][j] for i in range(len(w)) for j in range(len(w))) + sigma**2
            raw[name] = round(N01.cdf(lin / math.sqrt(var)), 4)
            scaled[name] = round(raw[name] * float(spec.get("scale", 1.0)), 4)
        return raw, scaled

    def bucket(self, axis: str, raw: float) -> str:
        """low / mid / high. A scaled-down axis only reaches "high" in the matching top share of players."""
        edge = float(self.cfg["bucket_edge"])
        scale = float(self.cfg["axes"].get(axis, {}).get("scale", 1.0))
        high = max(1 - edge, 1 - scale) if scale < 1 else 1 - edge
        return "low" if raw < edge else "high" if raw > high else "mid"

    def pick_goal(self, raw: dict[str, float], rng: random.Random) -> str:
        """Goals follow the unscaled axes; a scaled-down axis (leave x 0.1) makes the goals that lean on it that
        much rarer, without making the opposite goals more common."""
        scores = []
        for g in self.goals:
            s = float(g.get("weight", 1.0)) * math.exp(float(self.cfg["goal_affinity_strength"]) * sum(a * (raw.get(k, 0.5) - 0.5) for k, a in g["affinity"].items()))
            for k, a in g["affinity"].items():
                scale = float(self.cfg["axes"].get(k, {}).get("scale", 1.0))
                if a > 0 and scale < 1:
                    s *= scale
            scores.append(s)
        return rng.choices([g["id"] for g in self.goals], weights=scores)[0]

    def pick_stance(self, honesty: float, rng: random.Random) -> str:
        k = float(self.cfg.get("stance_power", 1))
        return rng.choices(["report", "cover", "hesitate"], weights=[honesty**k, (1 - honesty) ** k, float(self.cfg["stance_hesitate"])])[0]

    # -- the whole persona -------------------------------------------------------------------
    def generate_one(self, seed: int, index: int, render: str = "rules") -> Persona:
        rng = random.Random(f"{seed}:{index}")
        x, tails = self.sample_traits(rng)
        raw, scaled = self.axes(x, rng)
        side = rng.choices(list(self.cfg["side"]), weights=list(self.cfg["side"].values()))[0]
        st = self.cfg["style"]
        style = {
            "input_mode": "single" if rng.random() < st["input_mode_single"] else "channels",
            "temperature": round(rng.uniform(*st["temperature"]), 2),
        }
        identity = {"name": rng.choice(self.cfg["names"]), "gender": "female" if rng.random() < st["female"] else "male"}
        p = Persona(
            generator_version=int(self.cfg["generator_version"]),
            seed=seed,
            index=index,
            sampling={"tail": tails, "weight": round(self.weight(x), 4)},
            hexaco={d: round(v, 3) for d, v in zip(self.dims, x, strict=True)},
            axes=scaled,
            axes_raw=raw,
            side=side,
            goal=self.pick_goal(raw, rng),
            stance=self.pick_stance(scaled["honesty_to_nora"], rng),
            style=style,
            identity=identity,
        )
        p.card = self.render(p, rng, render)
        p.triggered = {"truth_out": [rng.choice(self.rules["stance"][p.stance])]}
        return p

    def generate(self, n: int, seed: int, render: str = "rules") -> list[Persona]:
        return [self.generate_one(seed, i, render) for i in range(n)]

    # -- rendering ----------------------------------------------------------------------------
    def render(self, p: Persona, rng: random.Random, mode: str = "rules") -> list[str]:
        goal = next(g["text"] for g in self.goals if g["id"] == p.goal)
        tail = [f"Your goal tonight: {goal}"]
        side = self._side_line(p, rng)
        if side:
            tail.append(side)
        tail.append(self.rules["style"][p.style["input_mode"]])
        if mode == "numeric":
            scores = ", ".join(f"{d} {v:+.1f}" for d, v in p.hexaco.items())
            return [f"{self.rules['numeric_header']} {scores}.", *tail]
        return [self._sketch(p, rng), *self._rules(p, rng), *tail]

    def card_at(self, p: Persona, state: dict[str, Any]) -> list[str]:
        """The card to send this turn: the opening card plus every triggered line whose condition holds."""
        out = list(p.card)
        for name, lines in p.triggered.items():
            rule = self.triggers.get(name)
            if rule is not None and truthy(rule, {**state, "turn": {}}):
                out += lines
        return out

    def _sketch(self, p: Persona, rng: random.Random) -> str:
        ranked = sorted(p.hexaco.items(), key=lambda kv: -abs(kv[1]))
        words = [rng.choice(self.rules["adjectives"][d]["high" if z > 0 else "low"])
                 for d, z in ranked if abs(z) >= float(self.cfg["adjective_min_z"])][: int(self.cfg["max_adjectives"])]
        words = words or [rng.choice(PLAIN)]
        return "You are " + (words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]) + "."

    def _rules(self, p: Persona, rng: random.Random) -> list[str]:
        buckets = {a: self.bucket(a, p.axes_raw[a]) for a in self.rules["rules"]}
        extremity = {a: abs(p.axes_raw[a] - 0.5) for a in buckets}
        picked: list[tuple[float, str]] = []
        used: set[str] = set()
        for combo in self.rules["combos"]:
            if all(buckets.get(a) == b for a, b in combo["when"].items()) and not used & set(combo["replaces"]):
                used |= set(combo["replaces"])
                picked.append((max(extremity[a] for a in combo["replaces"]), rng.choice(combo["text"])))
        for axis, b in buckets.items():
            texts = self.rules["rules"][axis].get(b) if b != "mid" else None
            if axis not in used and texts:
                picked.append((extremity[axis], rng.choice(texts)))
        picked.sort(key=lambda t: -t[0])
        return [t for _, t in picked[: int(self.cfg["max_rules"])]]

    def _side_line(self, p: Persona, rng: random.Random) -> str | None:
        texts = self.rules["side"][p.side].get(self.bucket("side_strength", p.axes_raw["side_strength"]))
        return rng.choice(texts) if texts else None


# --------------------------------------------------------------------------- statistics for the CLI and tests
def correlation(rows: list[list[float]], i: int, j: int, weights: list[float] | None = None) -> float:
    w = weights or [1.0] * len(rows)
    tw = sum(w)
    mi = sum(wk * r[i] for wk, r in zip(w, rows, strict=True)) / tw
    mj = sum(wk * r[j] for wk, r in zip(w, rows, strict=True)) / tw
    cov = sum(wk * (r[i] - mi) * (r[j] - mj) for wk, r in zip(w, rows, strict=True)) / tw
    vi = sum(wk * (r[i] - mi) ** 2 for wk, r in zip(w, rows, strict=True)) / tw
    vj = sum(wk * (r[j] - mj) ** 2 for wk, r in zip(w, rows, strict=True)) / tw
    return cov / math.sqrt(vi * vj)


def stats(gen: PersonaGenerator, personas: list[Persona]) -> dict[str, Any]:
    rows = [[p.hexaco[d] for d in gen.dims] for p in personas]
    weights = [p.sampling["weight"] for p in personas]
    n = len(personas)
    corr = {f"{gen.dims[i]}-{gen.dims[j]}": round(correlation(rows, i, j, weights), 3)
            for i, j in itertools.combinations(range(len(gen.dims)), 2)}
    buckets: dict[str, dict[str, float]] = {}
    for a in gen.rules["rules"]:
        counts = {"low": 0, "mid": 0, "high": 0}
        for p in personas:
            counts[gen.bucket(a, p.axes_raw[a])] += 1
        buckets[a] = {k: round(v / n, 3) for k, v in counts.items()}

    def share(key: str) -> dict[str, float]:
        out: dict[str, int] = {}
        for p in personas:
            out[str(getattr(p, key))] = out.get(str(getattr(p, key)), 0) + 1
        return {k: round(v / n, 3) for k, v in sorted(out.items(), key=lambda kv: -kv[1])}

    return {
        "n": n,
        "tail_share": round(sum(bool(p.sampling["tail"]) for p in personas) / n, 3),
        "mean_weight": round(sum(weights) / n, 3),
        "weighted_correlations": corr,
        "rule_buckets": buckets,
        "side": share("side"),
        "stance": share("stance"),
        "goals_top": dict(list(share("goal").items())[:8]),
        "distinct_cards": len({tuple(p.card) for p in personas}),
    }
