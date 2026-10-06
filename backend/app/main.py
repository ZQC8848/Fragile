"""FastAPI application. M0 skeleton: a health check and a WebSocket that says hello.

The REST surface and the turn protocol (interaction-design.md section 11, schemas/messages_v2.json) come
back in M1/M3 together with app/session.py.

Run:  uv run uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from engine.llm import load_env

# providers and keys live only in backend/.env (gitignored)
load_env()

log = logging.getLogger("fragile")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Fragile Drama Manager", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)


# ----------------------------------------------------------------------------- REST
@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"ok": True}


# ----------------------------------------------------------------------------- WebSocket
@app.websocket("/ws/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()

    async def push(msg: dict[str, Any]) -> None:
        await websocket.send_text(json.dumps(msg, ensure_ascii=False))

    await push({"type": "hello", "session": session_id})
    # M0: keep the connection open and ignore whatever the client sends until it disconnects.
    while True:
        msg = await websocket.receive()
        if msg["type"] == "websocket.disconnect":
            break
