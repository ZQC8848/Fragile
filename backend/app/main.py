"""FastAPI application: health, a few read-only REST views, and the turn protocol over WebSocket
(interaction-design.md §11, schemas/messages_v2.json).

Run:  uv run uvicorn app.main:app --reload --port 8000

One Session per session id; reconnecting to the same id resumes it. Several clients may watch one session (the
player's screen and the Console): every server message goes to all of them, each through its own filter. Every message the client sends is
validated against the client half of the protocol; a bad message gets an `error` back and changes nothing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import jsonschema
import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.session import Session, SessionError
from engine.llm import llm_roles, load_env
from engine.paths import DATA_DIR, REPO_ROOT, SCHEMAS_DIR

# providers and keys live only in backend/.env (gitignored)
load_env()

log = logging.getLogger("fragile")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Fragile Drama Manager", version="0.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

_PROTOCOL = json.loads((SCHEMAS_DIR / "messages_v2.json").read_text(encoding="utf-8"))
_CLIENT = jsonschema.Draft202012Validator({**_PROTOCOL, "oneOf": [{"$ref": "#/$defs/ClientToServer"}]})

#: the pre-game intro: premise, cast cards, player cards (interaction-design.md §10.4)
INTRO: dict[str, Any] = yaml.safe_load((DATA_DIR / "cast.yaml").read_text(encoding="utf-8"))
#: what really happened: only for a session that has ended
TRUTH: dict[str, Any] = yaml.safe_load((DATA_DIR / "truth.yaml").read_text(encoding="utf-8"))
#: messages only the Console gets: they carry the whole state, secrets included
CONSOLE_ONLY = {"drama_state", "turn_trace"}

# portraits, illustrations and the floor plan (art/, Git LFS)
app.mount("/art", StaticFiles(directory=REPO_ROOT / "art"), name="art")

SESSIONS: dict[str, Session] = {}
#: per session, the push function of every connected client
CLIENTS: dict[str, set[Any]] = {}


def _broadcaster(session_id: str):
    async def push(msg: dict[str, Any]) -> None:
        for client in list(CLIENTS.get(session_id, ())):
            try:
                await client(msg)
            except Exception:  # noqa: BLE001 - a closed socket must not stop the others or the turn
                CLIENTS.get(session_id, set()).discard(client)
    return push


def _session(session_id: str) -> Session:
    s = SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(404, f"no session {session_id!r}")
    return s


# ----------------------------------------------------------------------------- REST
@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "sessions": len(SESSIONS)}


@app.get("/api/intro")
async def intro() -> dict[str, Any]:
    """What the player reads before the session starts; the cast cards can be reopened in play."""
    return INTRO


@app.get("/api/sessions")
async def sessions() -> list[dict[str, Any]]:
    """Every session in this process, newest first, for the Console's picker."""
    rows = [{"id": sid, "phase": s.phase, "turn": s.state["turn_count"], "ending": s.state.get("ending"),
             "watchers": len(CLIENTS.get(sid, ()))} for sid, s in SESSIONS.items()]
    return rows[::-1]


@app.get("/api/sessions/{session_id}/truth")
async def truth(session_id: str) -> dict[str, Any]:
    """What really happened. Refused until that session has ended, so play never carries the answer."""
    if _session(session_id).phase != "ended":
        raise HTTPException(403, "the truth is shown after the ending")
    return TRUTH


@app.get("/api/sessions/{session_id}/state")
async def session_state(session_id: str) -> dict[str, Any]:
    return _session(session_id).drama_state()


@app.get("/api/sessions/{session_id}/turns")
async def session_turns(session_id: str) -> list[dict[str, Any]]:
    return _session(session_id).traces


@app.get("/api/llm")
async def llm() -> list[dict[str, Any]]:
    return llm_roles()


# ----------------------------------------------------------------------------- WebSocket
@app.websocket("/ws/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    # ?mode=play is the player's screen: it never receives the Console's state and turn records
    play = websocket.query_params.get("mode") == "play"

    async def push(msg: dict[str, Any]) -> None:
        if play and msg.get("type") in CONSOLE_ONLY:
            return
        await websocket.send_text(json.dumps(msg, ensure_ascii=False, default=str))

    session = SESSIONS.get(session_id)
    if session is None:
        session = SESSIONS[session_id] = Session(session_id, _broadcaster(session_id))
    else:
        session.push = _broadcaster(session_id)
    CLIENTS.setdefault(session_id, set()).add(push)
    await push({"type": "hello", "session": session_id})
    await push({"type": "session_state", "phase": session.phase, "turn": session.state["turn_count"]})
    try:
        while True:
            frame = await websocket.receive()
            if frame["type"] == "websocket.disconnect":
                break
            raw = frame.get("text")
            try:
                msg = json.loads(raw) if raw is not None else None
            except json.JSONDecodeError:
                msg = None
            if not isinstance(msg, dict):
                await push({"type": "error", "code": "bad_json", "message": "message is not a JSON object"})
                continue
            problems = [e.message for e in _CLIENT.iter_errors(msg)]
            if problems:
                await push({"type": "error", "code": "bad_message", "message": problems[0][:300]})
                continue
            try:
                await dispatch(session, msg)
            except SessionError as e:
                await push({"type": "error", "code": e.code, "message": str(e)})
            except Exception as e:  # noqa: BLE001 - one bad turn must not drop the connection
                log.exception("session %s: %s failed", session_id, msg.get("type"))
                await push({"type": "error", "code": "internal", "message": f"{e.__class__.__name__}: {e}"})
    except WebSocketDisconnect:
        pass
    finally:
        CLIENTS.get(session_id, set()).discard(push)


async def dispatch(session: Session, msg: dict[str, Any]) -> None:
    t = msg["type"]
    if t == "session_start":
        await session.start(msg["name"], msg["gender"])
    elif t == "input_review":
        await session.review({"mode": msg["mode"], "text": msg.get("text"), "channels": msg.get("channels")})
    elif t == "turn_submit":
        await session.submit(msg["channels"], msg["source"], msg.get("review_id"))
    elif t == "options_request":
        await session.request_options()
    elif t == "phone_open":
        session.logger.event("phone_open", {"turn": session.state["turn_count"]})
    elif t == "control":
        await session.control(msg["command"], msg.get("args"))
