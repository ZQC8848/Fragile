"""Generate task 2 data: self-play games where only the player and the review teacher are live.

Drives the group's engine (`app.session.Session`) the way tools/play_cli.py does. The narrator, guard,
scorer, tension and options roles stay on their offline mocks, so a game costs two API calls per turn:
the self-play player (role `selfplay`, Kimi) writes the input, the teacher (role `review`, DeepSeek)
labels it. The scene context the teacher saw is captured here, before each review, because the group's
logs do not record it yet.

    uv run python -m ml.task2.gen.run_selfplay --run smoke --games 2 --max-turns 5 --mock-player
    uv run python -m ml.task2.gen.run_selfplay --run pilot --games 3
    uv run python -m ml.task2.gen.run_selfplay --run b1 --games 50 --concurrency 8

Output (outside the repo): $TASK2_DATA/raw/<run>/turns.jsonl (one line per review call) and sessions.jsonl
(one line per game). Re-running the same --run skips games already marked done.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any

from engine.llm import load_env

from ..common.labels import SCHEMA_VERSION, SILENCE_UNIT

DATA_ROOT = Path(os.environ.get("TASK2_DATA", Path.home() / "fragile_task2_data"))
LANG_WEIGHTS = {"en": 0.8, "zh": 0.1, "mix": 0.1}


def _seed(run: str, i: int) -> int:
    return int(hashlib.sha1(f"{run}:{i}".encode()).hexdigest()[:12], 16)


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def _turn_input(out: dict[str, Any]) -> dict[str, Any] | None:
    """The player's output as a review input, or None for silence."""
    if out.get("mode") == "channels":
        ch = out.get("channels") or {}
        ch = {"speech": ch.get("speech") or "", "action": ch.get("action") or "", "expression": ch.get("expression") or "", "addressee": ch.get("addressee")}
        if not (ch["speech"] or ch["action"] or ch["expression"]):
            return None
        return {"mode": "channels", "channels": ch}
    text = (out.get("text") or "").strip()
    return {"mode": "single", "text": text} if text else None


class Generator:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.out = DATA_ROOT / "raw" / args.run
        self.out.mkdir(parents=True, exist_ok=True)
        self.lock = asyncio.Lock()
        self.sem_review = asyncio.Semaphore(args.review_slots)
        self.sem_player = asyncio.Semaphore(args.player_slots)
        self.calls = 0
        self.git_sha = _git_sha()
        self.done = self._done_sessions()
        from app.session import Session  # after env setup: role clients read LLM_LIVE_ROLES when created
        from engine.models.prompts import system_prompt

        from .player import PERSONAS, VIOLATIONS, LLMPlayer, MockPlayer

        self.Session = Session
        self.PERSONAS, self.VIOLATIONS, self.MockPlayer = PERSONAS, VIOLATIONS, MockPlayer
        self.llm_player = None if args.mock_player else LLMPlayer()
        self.review_prompt_chars: int | None = None
        self._system_prompt = system_prompt

    def _done_sessions(self) -> set[str]:
        path = self.out / "sessions.jsonl"
        if not path.exists():
            return set()
        return {json.loads(line)["session"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and json.loads(line)["status"] == "done"}

    def budget_left(self) -> bool:
        return self.args.max_calls <= 0 or self.calls < self.args.max_calls

    async def review(self, s, turn_input: dict[str, Any]):
        """Teacher review with retries: a fallback output (provider error or bad JSON twice) is never kept."""
        last = None
        for attempt in range(3):
            async with self.sem_review:
                self.calls += 1
                r = await s.review(turn_input)
            last = r
            if r.output is None or not r.output.fallback:
                return r, attempt
            await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"teacher kept falling back: {last.output.meta if last and last.output else None}")

    def _record(self, base: dict[str, Any], turn_input, ctx, r, attempt: int, retries: int, rule: dict, outcome: str, s) -> dict[str, Any]:
        teacher = None
        chars_in = chars_out = 0
        if r is not None and r.output is not None:
            teacher = {"data": r.output.data, "meta": r.output.meta, "fallback": r.output.fallback, "retries": retries}
            if self.review_prompt_chars is None:
                self.review_prompt_chars = len(self._system_prompt("review", ACTION_TABLE=s.world.action_table()).text)
            chars_in = self.review_prompt_chars + len(json.dumps({"input": turn_input, "context": ctx}, ensure_ascii=False))
            chars_out = len(json.dumps(r.output.data, ensure_ascii=False))
        return {
            **base,
            "attempt": attempt,
            "input": turn_input,
            "context": ctx,
            "passages_tail": [p["text"] for p in s.passages[-2:]],
            "precheck": r.precheck if r is not None else None,
            "silent": r is None,
            "teacher": teacher,
            "validity": r.validity if r is not None else {"label": "ok"},
            "rule": rule,
            "outcome": outcome,
            "ts": time.time(),
            "review_chars_in": chars_in,
            "review_chars_out": chars_out,
        }

    async def play(self, i: int) -> None:
        a = self.args
        sid = f"{a.run}-{i:04d}"
        if sid in self.done:
            return
        seed = _seed(a.run, i)
        rng = random.Random(seed)
        persona = self.PERSONAS[i % len(self.PERSONAS)]
        lang = rng.choices(list(LANG_WEIGHTS), weights=list(LANG_WEIGHTS.values()))[0]
        gender = rng.choice(["female", "male"])
        player = self.MockPlayer(seed) if a.mock_player else self.llm_player
        s = self.Session(sid, None, seed=seed, log_root=self.out / "logs", save_generated=False)
        await s.start("Sam", gender)
        rows: list[dict[str, Any]] = []
        stats = {"player_calls": 0, "review_calls": 0, "player_chars_in": 0, "player_chars_out": 0}
        t0 = time.time()
        status, error = "done", None
        vi = rng.randrange(len(self.VIOLATIONS))
        try:
            turn = 0
            while s.phase == "playing" and turn < a.max_turns:
                if not self.budget_left():
                    status = "budget"
                    break
                turn += 1
                mode = "single" if rng.random() < 0.8 else "channels"
                violate = None
                if rng.random() < 0.1:
                    violate = self.VIOLATIONS[vi % len(self.VIOLATIONS)]
                    vi += 1
                from .player import build_request

                req = build_request(s, persona, "Sam", mode, violate, lang)
                async with self.sem_player:
                    if not a.mock_player:
                        self.calls += 1
                    out, pmeta, cin, cout = await player.turn(req)
                stats["player_calls"] += 1
                stats["player_chars_in"] += cin
                stats["player_chars_out"] += cout
                base = {
                    "schema_version": SCHEMA_VERSION, "run": a.run, "session": sid, "game_seed": seed, "turn": turn,
                    "persona": persona, "lang": lang, "mode": mode, "violate_requested": violate,
                    "selfplay": {"output": out, "deliberate_violation": out.get("deliberate_violation"), "meta": pmeta},
                    "scene_notes": req["scene_notes"], "phone": req["phone"], "git_sha": self.git_sha,
                }
                turn_input = _turn_input(out)
                ctx = s._encoder_context()
                if turn_input is None:
                    rows.append(self._record(base, None, ctx, None, 0, 0, {}, "silence", s))
                    await s.submit({}, "filled", injected={"units": [dict(SILENCE_UNIT)]})
                    continue
                rule = s.encoder.rule.encode(turn_input, ctx)
                r, retries = await self.review(s, turn_input)
                stats["review_calls"] += 1 + retries
                if r.ok:
                    rows.append(self._record(base, turn_input, ctx, r, 0, retries, rule, "accepted", s))
                    await s.submit(r.channels, "typed_accepted", r.id)
                    continue
                rw = r.output.data.get("rewrite") if r.output is not None else None
                rows.append(self._record(base, turn_input, ctx, r, 0, retries, rule, "rejected" if rw else "rejected_no_rewrite", s))
                if not rw:
                    await s.submit({}, "filled", injected={"units": [dict(SILENCE_UNIT)]})
                    continue
                rw_input = {"mode": "channels", "channels": {k: rw.get(k) or ("" if k != "addressee" else None) for k in ("speech", "action", "expression", "addressee")}}
                ctx2 = s._encoder_context()
                r2, retries2 = await self.review(s, rw_input)
                stats["review_calls"] += 1 + retries2
                rows.append(self._record({**base, "source": "rewrite"}, rw_input, ctx2, r2, 1, retries2, s.encoder.rule.encode(rw_input, ctx2),
                                         "rewrite_accepted" if r2.ok else "rewrite_rejected", s))
                if r2.ok:
                    await s.submit(r2.channels, "typed_accepted", r2.id)
                else:
                    await s.submit({}, "filled", injected={"units": [dict(SILENCE_UNIT)]})
            if status == "done" and s.phase == "playing":
                status = "cut"
        except Exception as e:  # never keep a game with a bad label
            status, error = "failed", f"{type(e).__name__}: {e}"
            traceback.print_exc()
        summary = {
            "session": sid, "seed": seed, "persona": persona, "lang": lang, "gender": gender, "status": status, "error": error,
            "n_turns": len(rows), "ending": s.state.get("ending"), "latency_s": round(time.time() - t0, 1), **stats,
        }
        async with self.lock:
            if status in ("done", "cut"):
                with (self.out / "turns.jsonl").open("a", encoding="utf-8") as f:
                    for row in rows:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
            with (self.out / "sessions.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        print(f"[{sid}] {status} turns={len(rows)} ending={summary['ending']} {summary['latency_s']}s calls_total={self.calls}", flush=True)

    async def run(self) -> None:
        gate = asyncio.Semaphore(self.args.concurrency)

        async def one(i: int) -> None:
            async with gate:
                await self.play(i)

        await asyncio.gather(*(one(i) for i in range(self.args.start, self.args.start + self.args.games)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--games", type=int, default=3)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--max-turns", type=int, default=60)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--review-slots", type=int, default=6)
    ap.add_argument("--player-slots", type=int, default=4)
    ap.add_argument("--max-calls", type=int, default=0, help="stop starting new turns after this many API calls (0 = no limit)")
    ap.add_argument("--mock-player", action="store_true", help="offline smoke test: mock player and mock teacher, no API calls")
    args = ap.parse_args()

    load_env()
    os.environ["LLM_LIVE_ROLES"] = "" if args.mock_player else "review,selfplay"
    os.environ["MODEL_SHADOW"] = "0"
    os.environ["MODEL_ENCODER"] = "llm"
    os.environ["LLM_CACHE"] = "0"
    os.environ.setdefault("LLM_TIMEOUT_REVIEW", "30")
    os.environ.setdefault("LLM_TIMEOUT_SELFPLAY", "60")
    os.environ.setdefault("LLM_FALLBACK_SELFPLAY", "review")  # DeepSeek writes the turn when Kimi times out
    asyncio.run(Generator(args).run())


if __name__ == "__main__":
    main()
