"""The self-play runner (selfplay.md §7): plays a shard's sessions in-process, an LLM player against the real
turn loop, no frontend and no WebSocket.

    data/selfplay_raw/<round>/<shard>/<session>/    the session's own logs (turns, decisions, events,
                                                    session.json) plus
        persona.json      the manifest entry: persona, player model, DM policy, split, seed
        player.jsonl      one line per player attempt: what it saw (minus the passages), wrote, and what happened
        selfplay.json     status, ending, turns, tokens and cost per model, timings, git commit, prompt versions
    data/selfplay_raw/<round>/<shard>/_ledger.jsonl one line per session attempt with its cost: the budget

A session is done when its selfplay.json says ended, max_turns or error; running the same shard again skips
those and plays the rest from the start (an interrupted session is replayed whole; with the response cache
on, its earlier calls cost nothing). Errors are final unless --retry-errors.

Caps: --budget-usd stops starting sessions once the ledger reaches it, and aborts the running ones at 125%
(they are replayed next time). --max-tokens does the same on tokens, --max-sessions limits how many
sessions this invocation starts.
"""

from __future__ import annotations

import asyncio
import json
import random
import shutil
import subprocess
import time
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.session import Session
from engine.llm import USAGE, LLMOutputError, load_prompt
from engine.paths import DATA_DIR, REPO_ROOT

from .manifest import current_prompt_versions
from .persona import Persona, PersonaGenerator
from .profiles import Profile, Profiles

RAW_DIR = DATA_DIR / "selfplay_raw"
SCHEMA = json.loads((REPO_ROOT / "schemas" / "llm" / "selfplay.json").read_text(encoding="utf-8"))
VIOLATIONS = list(SCHEMA["properties"]["deliberate_violation"]["anyOf"][0]["enum"])
FINAL = {"ended", "max_turns", "error"}


class BudgetExceeded(RuntimeError):
    pass


def git_info() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False).stdout.strip()

    return {"commit": git("rev-parse", "HEAD") or None, "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def render_channels(ch: dict[str, Any]) -> str:
    parts = []
    if ch.get("action"):
        parts.append(ch["action"])
    if ch.get("speech"):
        parts.append(f'"{ch["speech"]}"')
    if ch.get("expression"):
        parts.append(f"({ch['expression']})")
    return " ".join(parts)


# =============================================================================================== the player
class Player:
    """The LLM guest of one session: builds what it sees each turn, asks the model, submits, handles refusals."""

    def __init__(self, entry: dict[str, Any], profile: Profile, gen: PersonaGenerator, run_cfg: dict[str, Any], log_path: Path,
                 *, cache: bool = True, mock_handler=None):
        self.entry = entry
        self.persona = Persona(**entry["persona"])
        self.gen = gen
        self.cfg = run_cfg
        self.prompt = load_prompt("selfplay")
        self.client = profile.client("selfplay", float(self.persona.style["temperature"]), cache=cache,
                                     mock_handler=mock_handler or mock_player)
        self.rng = random.Random(f"player:{entry['seed']}")
        self.log_path = log_path
        self.own: list[str] = []
        self.last_review: dict[str, Any] | None = None
        self.counts = {"calls": 0, "attempts": 0, "rejected": 0, "rewrites_accepted": 0, "llm_errors": 0, "silences": 0,
                       "violations_asked": 0}

    async def push(self, msg: dict[str, Any]) -> None:
        if msg.get("type") == "input_review_result":
            self.last_review = msg

    def view(self, s: Session, violate: str | None, refused: dict[str, Any] | None) -> dict[str, Any]:
        st = s.state
        card = s.card or {}
        return {
            "card": self.gen.card_at(self.persona, st),
            "player": {"name": s.name, "identity": card.get("identity"), "knows": card.get("knows", [])},
            "room": st["player_room"],
            "present": s.world.present(st),
            "passages": [p["text"] for p in s.passages[-int(self.cfg.get("passages", 6)):]],
            "your_recent_lines": self.own[-int(self.cfg.get("own_lines", 5)):],
            "phone": [{k: ev[k] for k in ("kind", "from", "text") if ev.get(k) is not None} for ev in s.phone],
            "mode": self.persona.style["input_mode"],
            "violate": violate,
            "refused": refused,
        }

    def _log(self, record: dict[str, Any]) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    async def turn(self, s: Session) -> dict[str, Any] | None:
        """Play one turn; returns the turn record (None only if even the silent fallback was refused)."""
        turn_no = s.state["turn_count"] + 1
        violate = None
        if self.rng.random() < float(self.persona.axes.get("violation_rate", 0)):
            violate = self.rng.choice(VIOLATIONS)
            self.counts["violations_asked"] += 1
        refused = None
        for attempt in range(1, int(self.cfg.get("max_attempts", 3)) + 1):
            self.counts["attempts"] += 1
            seen = self.view(s, violate if attempt == 1 else None, refused)
            log: dict[str, Any] = {"turn": turn_no, "attempt": attempt, "violate": seen["violate"], "refused": refused,
                                   "card_lines": len(seen["card"]), "room": seen["room"], "present": seen["present"]}
            self.counts["calls"] += 1
            try:
                res = await self.client.call_json(self.prompt.text, json.dumps(seen, ensure_ascii=False), schema=SCHEMA,
                                                  prompt_version=self.prompt.version)
            except LLMOutputError as e:
                self.counts["llm_errors"] += 1
                self._log({**log, "outcome": "llm_error", "llm": e.result.meta()})
                continue
            out = res.data
            log["llm"] = res.meta()
            log["output"] = out
            self.last_review = None
            record, outcome, line = await self._submit(s, out)
            if record is None and outcome == "rejected" and self.last_review:
                rw = self.last_review.get("rewrite")
                log["review"] = {k: self.last_review.get(k) for k in ("category", "message", "rewrite")}
                if rw and self.rng.random() < float(self.cfg.get("accept_rewrite", 0.5)):
                    record = await s.submit(rw, "typed_edited")
                    if record is not None:
                        outcome, line = "rewrite_accepted", render_channels(rw)
                        self.counts["rewrites_accepted"] += 1
            self._log({**log, "outcome": outcome})
            if record is not None:
                if line:
                    self.own.append(line)
                return record
            self.counts["rejected"] += 1
            r = self.last_review or {}
            refused = {"category": r.get("category"), "message": r.get("message")}
        self.counts["silences"] += 1
        self._log({"turn": turn_no, "attempt": 0, "outcome": "silence_fallback"})
        return await s.submit({}, "filled")

    async def _submit(self, s: Session, out: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str]:
        if out.get("mode") == "channels":
            ch = out.get("channels") or {}
            record = await s.submit(ch, "filled")
            return record, "played" if record is not None else "rejected", render_channels(ch)
        text = (out.get("text") or "").strip()
        review = await s.review({"mode": "single", "text": text})
        if not review.ok:
            return None, "rejected", text
        record = await s.submit(review.channels, "typed_accepted", review.id)
        return record, "played" if record is not None else "rejected", text


def mock_player(system: str, user: str) -> dict[str, Any]:
    """The offline player (profile `mock`): a few plain guest moves, picked by how far the evening is."""
    seen = json.loads(user.split("\n\nReply in json.")[0])
    lines = [
        'I take off my coat. "Something smells great."',
        'I look around the flat. "So this is it, the last night here?"',
        '"Has anyone heard from Leo?"',
        "I check my phone.",
        'I sit down at the crate. "To Australia."',
        '"Mia, how are you holding up?"',
        "I go out to the balcony.",
        "I go back inside.",
        '"Julian, what happened today?"',
        "",
    ]
    k = (len(seen.get("passages") or []) + len(seen.get("your_recent_lines") or []) * 3 + len(json.dumps(seen.get("present")))) % len(lines)
    text = lines[k]
    if seen.get("mode") == "channels":
        speech = text.split('"')[1] if '"' in text else ""
        action = text.split('"')[0].strip()
        return {"mode": "channels", "channels": {"speech": speech, "action": action, "expression": "", "addressee": None},
                "deliberate_violation": None}
    return {"mode": "single", "text": text, "deliberate_violation": None}


# =============================================================================================== spend
@dataclass
class Spend:
    """The shard's ledger: what every session attempt so far has cost, this run's included."""

    path: Path
    budget_usd: float | None = None
    max_tokens: int | None = None
    usd: float = 0.0
    tokens: int = 0
    live: dict[str, tuple[float, int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    self.usd += float(r.get("cost_usd", 0))
                    self.tokens += int(r.get("tokens", 0))

    def total(self) -> tuple[float, int]:
        return self.usd + sum(u for u, _ in self.live.values()), self.tokens + sum(t for _, t in self.live.values())

    def over(self, factor: float = 1.0) -> bool:
        usd, tokens = self.total()
        return bool((self.budget_usd is not None and usd >= self.budget_usd * factor)
                    or (self.max_tokens is not None and tokens >= self.max_tokens * factor))

    def close(self, session: str, status: str, usd: float, tokens: int) -> None:
        self.live.pop(session, None)
        self.usd += usd
        self.tokens += tokens
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"session": session, "status": status, "cost_usd": round(usd, 6), "tokens": tokens, "t": now()}) + "\n")


def usage_summary(usage: list[dict[str, Any]], profiles: Profiles) -> dict[str, Any]:
    by: dict[str, dict[str, Any]] = {}
    for u in usage:
        key = f"{u['provider']}:{u['model']}"
        row = by.setdefault(key, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "roles": {}})
        row["calls"] += 1
        row["input_tokens"] += int(u.get("input_tokens", 0))
        row["output_tokens"] += int(u.get("output_tokens", 0))
        row["roles"][u["role"]] = row["roles"].get(u["role"], 0) + 1
        p = profiles.price_of(u["provider"], u["model"])
        row["cost_usd"] += p.cost(int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0))) if p else 0.0
        row["priced"] = p is not None
    for row in by.values():
        row["cost_usd"] = round(row["cost_usd"], 6)
    return {
        "by_model": by,
        "tokens": sum(r["input_tokens"] + r["output_tokens"] for r in by.values()),
        "cost_usd": round(sum(r["cost_usd"] for r in by.values()), 6),
    }


# =============================================================================================== one session
async def play_session(entry: dict[str, Any], header: dict[str, Any], root: Path, profiles: Profiles, gen: PersonaGenerator,
                       spend: Spend, *, max_turns: int, cache: bool = True, git: dict[str, Any] | None = None,
                       mock_handler=None) -> dict[str, Any]:
    sid = entry["id"]
    d = root / sid
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "persona.json").write_text(json.dumps({**{k: header[k] for k in ("round", "tag") if k in header},
                                                "shard": header.get("shard"), **entry}, indent=1, ensure_ascii=False), encoding="utf-8")
    profile = profiles[entry["player_profile"]]
    usage: list[dict[str, Any]] = []
    token = USAGE.set(usage)
    t0 = time.perf_counter()
    info: dict[str, Any] = {
        "session": sid, "round": header.get("round"), "shard": header.get("shard"), "status": "running",
        "split": entry["split"], "player_profile": profile.name, "player_model": profile.model or profile.provider,
        "dm": entry["dm"], "started": now(), "git": git or git_info(), "prompt_versions": current_prompt_versions(),
        "generator_version": entry["persona"]["generator_version"], "profiles_hash": profiles.hash,
    }

    def write(**extra: Any) -> dict[str, Any]:
        info.update(extra)
        info["usage"] = usage_summary(usage, profiles)
        info["wall_s"] = round(time.perf_counter() - t0, 1)
        (d / "selfplay.json").write_text(json.dumps(info, indent=1, ensure_ascii=False), encoding="utf-8")
        return info

    player = Player(entry, profile, gen, profiles.run, d / "player.jsonl", cache=cache, mock_handler=mock_handler)
    try:
        s = Session(sid, player.push, seed=int(entry["seed"]), scorer=entry["dm"]["scorer"], tau=float(entry["dm"]["tau"]),
                    log_root=root, save_generated=False)
        ident = entry["persona"]["identity"]
        await s.start(ident["name"], ident["gender"])
        write()
        while s.phase == "playing" and s.state["turn_count"] < max_turns:
            before = s.state["turn_count"]
            await player.turn(s)
            if s.state["turn_count"] == before and s.phase == "playing":
                raise RuntimeError("the turn did not advance, even in silence")
            u = usage_summary(usage, profiles)
            spend.live[sid] = (u["cost_usd"], u["tokens"])
            write(turns=s.state["turn_count"], player=player.counts)
            if spend.over(1.25):
                raise BudgetExceeded("budget exceeded by 25%: session aborted, it is replayed next run")
        status = "ended" if s.phase == "ended" else "max_turns"
        write(status=status, ending=s.state.get("ending"), turns=s.state["turn_count"], story_min=s.state["story_min"],
              player=player.counts, finished=now())
    except BudgetExceeded as e:
        write(status="aborted", error=str(e), player=player.counts, finished=now())
    except Exception as e:  # noqa: BLE001 - one session's crash is recorded and never stops the shard
        write(status="error", error=f"{e.__class__.__name__}: {e}", traceback=traceback.format_exc()[-4000:],
              player=player.counts, finished=now())
    finally:
        USAGE.reset(token)
    spend.close(sid, info["status"], info["usage"]["cost_usd"], info["usage"]["tokens"])
    return info


# =============================================================================================== a shard
def session_status(d: Path) -> str | None:
    f = d / "selfplay.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("status")
    except json.JSONDecodeError:
        return None


def available(profile: Profile) -> tuple[bool, str]:
    if profile.provider == "mock":
        return True, "mock"
    if profile.is_cli:
        ok = profile.config("selfplay", 1.0).can_go_live()
        return ok, "installed" if ok else f"{profile.provider}: command not found"
    return (True, "key set") if profile.key() else (False, f"no key ({' or '.join(profile.key_env)})")


async def run_shard(manifest: dict[str, Any], *, raw_dir: Path = RAW_DIR, profiles: Profiles | None = None,
                    concurrency: int | None = None, budget_usd: float | None = None, max_tokens: int | None = None,
                    max_sessions: int | None = None, max_turns: int | None = None, retry_errors: bool = False,
                    only: set[str] | None = None, cache: bool = True, mock_handler=None, progress=print) -> dict[str, Any]:
    prof = profiles or Profiles()
    prof.apply_engine_roles(cache=cache)
    gen = PersonaGenerator()
    shard = manifest.get("shard") or "all"
    root = Path(raw_dir) / manifest["round"] / shard
    root.mkdir(parents=True, exist_ok=True)
    spend = Spend(root / "_ledger.jsonl", budget_usd, max_tokens)
    git = git_info()
    max_turns = int(max_turns or prof.run.get("max_turns", 60))

    for role, name in prof.engine_roles.items():
        ok, why = available(prof[name])
        if not ok:
            raise RuntimeError(f"engine role {role} ({name}) is not usable here: {why}; run `python -m selfplay doctor`")

    todo, skipped, unavailable = [], [], {}
    for entry in manifest["sessions"]:
        if only and entry["id"] not in only:
            continue
        status = session_status(root / entry["id"])
        if status in FINAL and not (retry_errors and status == "error"):
            skipped.append(entry["id"])
            continue
        if status in ("running", "aborted"):
            # an interrupted attempt: book what its partial record says it spent before it is replayed
            info = json.loads((root / entry["id"] / "selfplay.json").read_text(encoding="utf-8"))
            if status == "running":
                spend.close(entry["id"], "interrupted", info.get("usage", {}).get("cost_usd", 0), info.get("usage", {}).get("tokens", 0))
        ok, why = available(prof[entry["player_profile"]])
        if not ok:
            unavailable[entry["id"]] = why
            continue
        todo.append(entry)
    if max_sessions is not None:
        todo = todo[:max_sessions]

    sem = asyncio.Semaphore(int(concurrency or prof.run.get("concurrency", 6)))
    per_profile = {n: asyncio.Semaphore(p.concurrency) for n, p in prof.profiles.items() if p.concurrency}
    results: list[dict[str, Any]] = []
    not_started: list[str] = []

    async def one(entry: dict[str, Any]) -> None:
        gate = per_profile.get(entry["player_profile"])
        if gate is not None:
            await gate.acquire()
        try:
            async with sem:
                if spend.over():
                    not_started.append(entry["id"])
                    return
                progress(f"start  {entry['id']}  {entry['player_profile']}  dm {entry['dm']['policy']}  {entry['split']}")
                info = await play_session(entry, manifest, root, prof, gen, spend, max_turns=max_turns, cache=cache, git=git,
                                          mock_handler=mock_handler)
                results.append(info)
                usd, _ = spend.total()
                progress(f"{info['status']:<9} {entry['id']}  ending {info.get('ending')}  turns {info.get('turns')}  "
                         f"{info['wall_s']:.0f}s  ${info['usage']['cost_usd']:.3f}  (shard ${usd:.2f})")
        finally:
            if gate is not None:
                gate.release()

    await asyncio.gather(*(one(e) for e in todo))
    usd, tokens = spend.total()
    return {
        "round": manifest["round"], "shard": shard, "dir": str(root), "played": len(results),
        "statuses": {k: sum(r["status"] == k for r in results) for k in sorted({r["status"] for r in results})},
        "skipped_done": len(skipped), "unavailable": unavailable, "not_started_budget": not_started,
        "spent_usd": round(usd, 4), "tokens": tokens, "git": git,
    }
