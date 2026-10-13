"""Play Fragile in the terminal, against the same Session the WebSocket uses (plan.md M3).

    uv run python tools/play_cli.py [--name Sam] [--gender female|male|nonbinary] [--seed 1] [--scorer A|B|C|random]
                                    [--live all | --live review,narrator,guard]

Without --live every LLM role answers from its offline mock (unless backend/.env lists it in LLM_LIVE_ROLES).
--live all sends every role to the provider configured in backend/.env.

Type what you say and do in one line ("I lean on the railing. "Isn't that Leo's car?""). Quotes are speech,
the rest is action. The draft comes back split into channels: Enter sends it, `e` edits the channels, anything
else replaces it. An empty line is silence.

Commands (free, they never use up a turn):
    /channels   switch between the single box and filling in the channels
    /options    three suggested moves; pick 1-3, or e1-e3 to edit one first
    /phone      the phone drawer: missed calls, voicemail, texts
    /state      story state, current beat and step
    /trace      the last turn: input, M2, world, reactions, beat, clock, DM, narrator, guard, latencies
    /help, /quit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import textwrap
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.session import Session, SessionError  # noqa: E402
from engine.llm import load_env  # noqa: E402

ReadLine = Callable[[str], Awaitable[str | None]]
Write = Callable[[str], None]

ADDRESSEES = ("julian", "mia", "both", "nora", "self")


async def stdin_line(prompt: str) -> str | None:
    try:
        return await asyncio.to_thread(input, prompt)
    except EOFError:
        return None


def render_segments(segments: list[dict[str, Any]]) -> str:
    parts = []
    for s in segments:
        if s["kind"] == "speech":
            parts.append(f"{(s.get('speaker') or '?').capitalize()}: \"{s['text']}\"")
        elif s["kind"] == "me_speech":
            parts.append(f"\"{s['text']}\"")
        else:
            parts.append(s["text"])
    return " ".join(parts)


def render_channels(ch: dict[str, Any]) -> str:
    bits = []
    if ch.get("action"):
        bits.append(f"do: {ch['action']}")
    if ch.get("expression"):
        bits.append(f"face: {ch['expression']}")
    if ch.get("speech"):
        bits.append(f"say: \"{ch['speech']}\"")
    if ch.get("addressee"):
        bits.append(f"to {ch['addressee']}")
    return " · ".join(bits) or "(silence)"


class Cli:
    def __init__(self, read: ReadLine, write: Write, **session_kw: Any):
        self.read = read
        self.write = write
        self.width = min(100, shutil.get_terminal_size((100, 20)).columns)
        self.session = Session(session_kw.pop("session_id", "cli"), self.on_message, **session_kw)
        self.mode = "single"
        self.last_review: dict[str, Any] | None = None
        self.options: list[dict[str, Any]] = []

    # -- output -----------------------------------------------------------------------------
    def say(self, text: str = "", indent: str = "") -> None:
        if not text:
            self.write("")
            return
        for para in text.split("\n"):
            self.write(textwrap.fill(para, self.width, initial_indent=indent, subsequent_indent=indent) if para else "")

    async def on_message(self, msg: dict[str, Any]) -> None:
        t = msg["type"]
        if t == "passage":
            self.say()
            if msg.get("player"):
                self.say(f"[you · {render_channels(msg['player'])}]", "  ")
            self.say(render_segments(msg["segments"]))
            if msg.get("tableau"):
                self.say(f"[picture: {msg['tableau']}]", "  ")
        elif t == "input_review_result":
            self.last_review = msg
        elif t == "options":
            self.options = msg["items"]
        elif t == "phone_event" and msg["kind"] in ("text", "call_incoming"):
            self.say(f"[phone · {msg['kind'].replace('_', ' ')} from {msg['from']}]", "  ")
        elif t == "room_state":
            who = ", ".join(p.capitalize() for p in msg["present"]) or "nobody"
            self.say(f"[{msg['player_room']} · {who}]", "  ")
        elif t == "session_state" and msg["phase"] == "ended":
            self.say("\n— the end —")
        elif t == "error":
            self.say(f"[error: {msg['message']}]")

    # -- the loop ---------------------------------------------------------------------------
    async def run(self, name: str, gender: str) -> None:
        for line in __doc__.split("Commands")[0].split("\n\n", 1)[1].strip().splitlines():
            self.write(line)
        await self.session.start(name, gender)
        while self.session.phase == "playing":
            line = await self.read("\n> " if self.mode == "single" else "\n(channels) > ")
            if line is None:
                break
            line = line.strip()
            try:
                if line.startswith("/"):
                    if not await self.command(line):
                        break
                elif self.mode == "channels":
                    await self.fill_channels(first=line)
                elif not line:
                    await self.session.submit({}, "filled")
                else:
                    await self.single(line)
            except SessionError as e:
                self.say(f"[{e.code}: {e}]")

    async def command(self, line: str) -> bool:
        cmd = line.split()[0].lower()
        if cmd in ("/quit", "/exit"):
            return False
        if cmd == "/help":
            for line in ("Commands" + __doc__.split("Commands", 1)[1]).rstrip().splitlines():
                self.write(line)
        elif cmd == "/channels":
            self.mode = "channels" if self.mode == "single" else "single"
            self.say(f"[input mode: {self.mode}]")
        elif cmd == "/options":
            await self.pick_option()
        elif cmd == "/phone":
            self.session.logger.event("phone_open", {"turn": self.session.state["turn_count"]})
            for ev in self.session.phone:
                body = f": {ev['text']}" if ev.get("text") and ev["kind"] != "missed_call" else ""
                self.say(f"{ev['kind'].replace('_', ' ')} · {ev['from'].capitalize()}{body}", "  ")
            if self.session.state["nora_call"] == "ringing":
                self.say("Nora is calling. (answer or decline it as your action)", "  ")
        elif cmd == "/state":
            s = self.session
            self.say(s.schema.textualize(s.state), "  ")
            self.say(f"run: {json.dumps(s.run.public() if s.run else None)}", "  ")
            self.say(f"tension measured {s.tension_measured:.2f} · arc target {s.dm.arc.target_at(s.state['story_min']):.2f}", "  ")
        elif cmd == "/trace":
            self.trace()
        else:
            self.say(f"[unknown command {cmd}; /help]")
        return True

    async def single(self, text: str) -> None:
        while True:
            review = await self.session.review({"mode": "single", "text": text})
            msg = review.message()
            if msg["verdict"] == "rejected":
                self.say(f"[{msg.get('category')}] {msg.get('message') or ''}", "  ")
                rw = msg.get("rewrite")
                if rw:
                    self.say(f"rewrite: {render_channels(rw)}", "  ")
                    ans = await self.read("  Enter = use the rewrite · or type again > ")
                    if ans is None:
                        return
                    if not ans.strip():
                        await self.session.submit(rw, "typed_edited")
                        return
                    text = ans.strip()
                    continue
                ans = await self.read("  type again (Enter to drop it) > ")
                if not ans or not ans.strip():
                    return
                text = ans.strip()
                continue
            draft = msg["channels"]
            note = " (translated)" if msg.get("translated") else ""
            self.say(f"draft{note}: {render_channels(draft)}", "  ")
            ans = await self.read("  Enter = send · e = edit channels · or type again > ")
            if ans is None:
                return
            if not ans.strip():
                await self.session.submit(draft, "typed_accepted", review.id)
                return
            if ans.strip().lower() == "e":
                await self.fill_channels(prefill=draft, source="typed_edited")
                return
            text = ans.strip()

    async def fill_channels(self, first: str | None = None, prefill: dict[str, Any] | None = None, source: str = "filled") -> None:
        pre = prefill or {}
        ch: dict[str, Any] = {}
        for key, label in (("speech", "say"), ("action", "do"), ("expression", "face")):
            if key == "speech" and first is not None and prefill is None:
                ch[key] = first
                continue
            ans = await self.read(f"  {label} [{pre.get(key) or ''}] > ")
            ch[key] = (pre.get(key) or "") if not ans else ans.strip()
        present = self.session.world.present(self.session.state)
        choices = [a for a in ADDRESSEES if a in present or a in ("both", "self")]
        ans = await self.read(f"  to ({'/'.join(choices)}) [{pre.get('addressee') or ''}] > ")
        ans = (ans or "").strip().lower()
        ch["addressee"] = ans if ans in ADDRESSEES else pre.get("addressee")
        await self.session.submit(ch, source)

    async def pick_option(self) -> None:
        await self.session.request_options()
        for i, o in enumerate(self.options, 1):
            self.say(f"{i}. {render_channels(o)}", "  ")
        ans = (await self.read("  pick 1-3 · e1-e3 to edit · Enter to skip > ") or "").strip().lower()
        edit = ans.startswith("e")
        idx = ans[1:] if edit else ans
        if not idx.isdigit() or not 1 <= int(idx) <= len(self.options):
            return
        chosen = self.options[int(idx) - 1]
        if edit:
            await self.fill_channels(prefill=chosen, source="option_edited")
        else:
            await self.session.submit(chosen, "option")

    def trace(self) -> None:
        if not self.session.traces:
            self.say("[no turns yet]")
            return
        r = self.session.traces[-1]
        u = r.get("understanding") or {}
        rows = [
            ("turn", r["turn"]),
            ("input", (r.get("input") or {}).get("source")),
            ("units", [(x.get("act"), x.get("action")) for x in u.get("units", [])]),
            ("claims", u.get("claims")),
            ("world", {k: v for k, v in (r.get("world") or {}).items() if v and k != "effects"}),
            ("reaction", (r.get("reactions") or {}).get("primary", {}) and r["reactions"]["primary"]["id"]),
            ("secondary", (r.get("reactions") or {}).get("secondary") and r["reactions"]["secondary"]["id"]),
            ("beat", r.get("beat")),
            ("clock", r.get("clock")),
            ("decision", r.get("decision") and {k: r["decision"][k] for k in ("kind", "chosen", "reasoning")}),
            ("guard", [(g["attempt"], g["steps_ok"]) for g in r.get("guard") or []]),
            ("state diff", r.get("state_diff")),
            ("latency ms", r.get("latency_ms")),
            ("llm calls", [f"{c['role']}:{c['model']}@v{c['prompt_version']} {c['latency_ms']:.0f}ms x{c['attempts']}" for c in r.get("llm_calls") or []]),
        ]
        for k, v in rows:
            self.say(f"{k:>10}: {json.dumps(v, ensure_ascii=False, default=str)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Play Fragile in the terminal.")
    ap.add_argument("--name", default=None)
    ap.add_argument("--gender", default=None, choices=["female", "male", "nonbinary"])
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--scorer", default=None, help="A|B|C|random (default: MODEL_SCORER or B)")
    ap.add_argument("--tau", type=float, default=1.0)
    ap.add_argument("--live", default=None, help="roles to send to their real provider: all, or a comma list")
    args = ap.parse_args()
    load_env()
    if args.live:
        from engine.llm import ROLES

        os.environ["LLM_LIVE_ROLES"] = ",".join(ROLES) if args.live == "all" else args.live

    async def go() -> None:
        name = args.name or (await stdin_line("Your name: ") or "Sam").strip() or "Sam"
        gender = args.gender or ((await stdin_line("Gender (female/male/nonbinary): ") or "").strip().lower() or "nonbinary")
        if gender not in ("female", "male", "nonbinary"):
            gender = "nonbinary"
        cli = Cli(stdin_line, print, seed=args.seed, scorer=args.scorer, tau=args.tau)
        await cli.run(name, gender)

    asyncio.run(go())


if __name__ == "__main__":
    main()
