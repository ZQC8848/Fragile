"""FastAPI application: health, a few read-only REST views, and the turn protocol over WebSocket
(interaction-design.md §11, schemas/messages_v2.json).

Run:  uv run uvicorn app.main:app --reload --port 8000

One Session per session id; reconnecting to the same id resumes it. Every message the client sends is
validated against the client half of the protocol; a bad message gets an `error` back and changes nothing.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import jsonschema
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.session import Session, SessionError
from engine.llm import llm_roles, load_env
from engine.paths import SCHEMAS_DIR

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

SESSIONS: dict[str, Session] = {}


def _session(session_id: str) -> Session:
    s = SESSIONS.get(session_id)
    if s is None:
        raise HTTPException(404, f"no session {session_id!r}")
    return s


# ----------------------------------------------------------------------------- REST
@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "sessions": len(SESSIONS)}


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

    async def push(msg: dict[str, Any]) -> None:
        await websocket.send_text(json.dumps(msg, ensure_ascii=False, default=str))

    session = SESSIONS.get(session_id)
    if session is None:
        session = SESSIONS[session_id] = Session(session_id, push)
    else:
        session.push = push
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
