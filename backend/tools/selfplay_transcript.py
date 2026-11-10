"""One self-play session as readable text, optionally in Chinese.

    uv run python -m selfplay transcript pilot-0003 --round pilot            # writes transcript.md
    uv run python -m selfplay transcript pilot-0003 --round pilot --zh       # also transcript.zh.md

Reads the session from data/selfplay_raw/<round>/*/<session>/ (or from its pack in data/selfplay/ with
--packed). The English transcript is deterministic: the player's persona and goal, then each turn with what the
player wrote (and any attempts the reviewer refused) and the passage the narrator wrote back. The Chinese
one translates every player line and passage with deepseek-flash in a few batched calls (cached, so
asking again is free); character names stay in English.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from engine.llm import LLMOutputError
from selfplay.pack import PACKS_DIR, read_pack
from selfplay.run import RAW_DIR, render_channels

BATCH = 8  # strings per translation call
SCHEMA = {"type": "object", "required": ["translations"], "properties": {"translations": {"type": "array", "items": {"type": "string"}}}}
SYSTEM = (
    "You translate English text from an interactive drama into natural, literary Chinese. The text is a first-person "
    "game transcript (a farewell dinner among old friends). Keep character names (Julian, Mia, Nora, Leo) and the "
    "player's name in English. Keep quotation marks around spoken lines. Do not add, explain or censor anything. "
    "The input is a JSON list of strings; reply with JSON {\"translations\": [...]} holding exactly one Chinese string "
    "per input string, in the same order."
)
ROOMS = {"hall": ("hall", "门厅"), "living": ("living room", "客厅"), "kitchen": ("kitchen", "厨房"), "balcony": ("balcony", "阳台"),
         "bedroom": ("bedroom", "卧室"), "bathroom": ("bathroom", "卫生间"), "outside": ("outside", "门外")}


def load_session(session: str, round_name: str, *, packed: bool = False) -> dict[str, Any]:
    if packed:
        found = sorted((PACKS_DIR / round_name).glob(f"*/{session}.tar.gz"))
        if not found:
            raise FileNotFoundError(f"no pack for {session} in {PACKS_DIR / round_name}")
        return read_pack(found[0])
    found = sorted((RAW_DIR / round_name).glob(f"*/{session}"))
    if not found:
        raise FileNotFoundError(f"no session {session} in {RAW_DIR / round_name}")
    d = found[0]
    out: dict[str, Any] = {}
    for f in d.iterdir():
        if f.suffix == ".jsonl":
            out[f.name] = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
        elif f.suffix == ".json":
            out[f.name] = json.loads(f.read_text(encoding="utf-8"))
    out["_dir"] = d
    return out


# ----------------------------------------------------------------------------------------------- the document
def _passage(rec: dict[str, Any]) -> list[tuple[str, str | None, str]]:
    """The narrator's part of a turn as (kind, speaker, text); the player's own echoed lines are left out."""
    return [(s["kind"], s.get("speaker"), s["text"]) for s in rec["narrator"]["segments"] if not s["kind"].startswith("me")]


def build(s: dict[str, Any]) -> list[dict[str, Any]]:
    """The transcript as blocks: {"type": "heading|text|player|note|passage|rule", ...}. Strings to translate sit under
    the keys listed in TRANSLATE."""
    persona_file = s["persona.json"]
    persona = persona_file["persona"]
    info = s["selfplay.json"]
    blocks: list[dict[str, Any]] = [
        {"type": "title", "text": f"{persona_file['id']} · {info['player_profile']} · DM {info['dm']['policy']} · ending {info.get('ending')}"},
        {"type": "meta", "text": f"Player: {persona['identity']['name']} ({persona['identity']['gender']}) · split {persona_file['split']} · "
                                 f"{info.get('turns')} turns · {info.get('wall_s', 0) / 60:.0f} min · ${info['usage']['cost_usd']:.2f}",
         "zh": f"玩家：{persona['identity']['name']}（{'男' if persona['identity']['gender'] == 'male' else '女'}）· {persona_file['split']} 集 · "
               f"{info.get('turns')} 回合 · {info.get('wall_s', 0) / 60:.0f} 分钟 · ${info['usage']['cost_usd']:.2f}"},
        {"type": "heading", "text": "Persona card"},
        *({"type": "bullet", "text": line} for line in persona["card"]),
        {"type": "bullet", "text": f"(held back until the truth is out) {persona['triggered']['truth_out'][0]}" if persona.get("triggered") else ""},
    ]
    attempts: dict[int, list[dict[str, Any]]] = {}
    for a in s.get("player.jsonl", []):
        attempts.setdefault(a["turn"], []).append(a)
    for rec in s["turns.jsonl"]:
        n = rec["turn"]
        state = rec["state"]
        beat = (rec.get("beat") or {})
        beat_id = ((beat.get("run") or beat.get("ended") or {}).get("beat_id")) or ""
        blocks.append({"type": "heading", "text": f"Turn {n}" if n else "Opening", "turn": n, "minute": state["story_min"],
                       "room": state["player_room"], "beat": beat_id})
        if n:
            for a in attempts.get(n, []):
                if a["outcome"] in ("rejected", "llm_error", "silence_fallback"):
                    why = (a.get("review") or {}).get("message") or ""
                    blocks.append({"type": "note", "text": f"attempt {a['attempt']} not played ({a['outcome']}){': ' + why if why else ''}"})
            ch = rec["input"]["channels"]
            line = render_channels(ch) or "(says and does nothing)"
            addressee = f" → {ch['addressee']}" if ch.get("addressee") else ""
            violate = next((a.get("violate") for a in attempts.get(n, []) if a.get("violate")), None)
            blocks.append({"type": "player", "text": line, "tail": addressee + (f"  [asked to break a rule: {violate}]" if violate else "")})
        for kind, speaker, text in _passage(rec):
            blocks.append({"type": "passage", "kind": kind, "speaker": speaker, "text": text})
        if state.get("ending") and rec is s["turns.jsonl"][-1]:
            blocks.append({"type": "rule", "text": f"Ending: {state['ending']}"})
    return blocks


TRANSLATE = ("text",)
NO_TRANSLATE = {"title", "rule", "heading"}


def strings_to_translate(blocks: list[dict[str, Any]]) -> list[str]:
    return [b["text"] for b in blocks if b["type"] not in NO_TRANSLATE and b.get("text") and not b.get("zh")]


def to_markdown(blocks: list[dict[str, Any]], zh: dict[str, str] | None = None) -> str:
    t = (lambda x: zh.get(x, x)) if zh else (lambda x: x)
    labels = {"player": "玩家", "ending": "结局"} if zh else {}
    out: list[str] = []
    for b in blocks:
        ty = b["type"]
        if ty == "title":
            out.append(f"# {b['text']}\n")
        elif ty == "meta":
            out.append(f"{b['zh'] if zh and b.get('zh') else t(b['text'])}\n")
        elif ty == "bullet":
            if b["text"]:
                out.append(f"- {t(b['text'])}")
        elif ty == "heading":
            if b["text"] == "Persona card":
                out.append("\n## " + ("玩家人格卡" if zh else "Persona card") + "\n")
            else:
                room = ROOMS.get(b["room"], (b["room"], b["room"]))
                if zh:
                    head = "开场" if not b["turn"] else f"回合 {b['turn']}"
                    sub = f"剧情第 {b['minute']:g} 分钟 · {room[1]}" + (f" · 拍 {b['beat']}" if b["beat"] else "")
                else:
                    head = b["text"]
                    sub = f"story minute {b['minute']:g} · {room[0]}" + (f" · beat {b['beat']}" if b["beat"] else "")
                out.append(f"\n## {head}  \n<sub>{sub}</sub>\n")
        elif ty == "note":
            out.append(f"*{t(b['text'])}*\n")
        elif ty == "player":
            out.append(f"**{labels.get('player', 'Player')}：** {t(b['text'])}{b['tail']}\n" if zh else f"**Player:** {b['text']}{b['tail']}\n")
        elif ty == "passage":
            if b["kind"] == "speech":
                out.append(f"**{b['speaker'].capitalize()}：** {t(b['text'])}\n" if zh else f"**{b['speaker'].capitalize()}:** {b['text']}\n")
            else:
                out.append(f"{t(b['text'])}\n")
        elif ty == "rule":
            out.append(f"\n---\n**{labels.get('ending', 'Ending') + '：' if zh else 'Ending: '}{b['text'].split(': ', 1)[1]}**\n")
    return "\n".join(out)


# ----------------------------------------------------------------------------------------------- translation
async def translate(strings: list[str], *, cache: bool = True, progress=print) -> dict[str, str]:
    from selfplay.profiles import Profiles

    prof = Profiles()
    client = prof["deepseek-flash"].client("selfplay", 0.2, cache=cache)
    unique = list(dict.fromkeys(strings))
    out: dict[str, str] = {}

    async def run(chunk: list[str]) -> None:
        try:
            res = await client.call_json(SYSTEM, json.dumps(chunk, ensure_ascii=False), schema=SCHEMA, prompt_version=1)
            got = res.data["translations"]
        except LLMOutputError:  # an empty or cut-off reply: a smaller batch usually fits
            if len(chunk) == 1:
                raise
            got = []
        if len(got) == len(chunk):
            out.update(zip(chunk, got, strict=True))
        elif len(chunk) == 1:
            raise RuntimeError("the translator returned the wrong number of strings for a single string")
        else:  # a count mismatch: split the chunk and ask again
            mid = len(chunk) // 2
            await run(chunk[:mid])
            await run(chunk[mid:])

    chunks = [unique[i : i + BATCH] for i in range(0, len(unique), BATCH)]
    sem = asyncio.Semaphore(4)

    async def guarded(i: int, chunk: list[str]) -> None:
        async with sem:
            await run(chunk)
            progress(f"translated {min((i + 1) * BATCH, len(unique))}/{len(unique)}")

    await asyncio.gather(*(guarded(i, c) for i, c in enumerate(chunks)))
    return out


def write(session: str, round_name: str, *, zh: bool = False, packed: bool = False, cache: bool = True, out_dir: Path | None = None,
          progress=print) -> list[Path]:
    s = load_session(session, round_name, packed=packed)
    blocks = build(s)
    d = Path(out_dir) if out_dir else s.get("_dir") or (RAW_DIR / round_name)
    d.mkdir(parents=True, exist_ok=True)
    paths = [d / "transcript.md"]
    paths[0].write_text(to_markdown(blocks), encoding="utf-8")
    if zh:
        from engine.llm import load_env

        load_env()
        mapping = asyncio.run(translate(strings_to_translate(blocks), cache=cache, progress=progress))
        paths.append(d / "transcript.zh.md")
        paths[1].write_text(to_markdown(blocks, mapping), encoding="utf-8")
    return paths
