"""The WebSocket speaks protocol v2 (schemas/messages_v2.json): every server message validates, bad client
messages get an error and change nothing, and a session can be started and played over the socket."""

from __future__ import annotations

import json

import jsonschema
import pytest
from fastapi.testclient import TestClient
from helpers import SCHEMAS

import app.main as main_mod
from app.main import app

PROTOCOL = json.loads((SCHEMAS / "messages_v2.json").read_text(encoding="utf-8"))
SERVER = jsonschema.Draft202012Validator({**PROTOCOL, "oneOf": [{"$ref": "#/$defs/ServerToClient"}]})


@pytest.fixture(autouse=True)
def fresh_sessions(monkeypatch):
    monkeypatch.setattr(main_mod, "SESSIONS", {})
    monkeypatch.setattr(main_mod, "CLIENTS", {})


def receive_until(ws, type_: str, limit: int = 60) -> list[dict]:
    """Every message up to and including the first of `type_`, each checked against the protocol."""
    out = []
    for _ in range(limit):
        msg = ws.receive_json()
        assert not list(SERVER.iter_errors(msg)), (msg["type"], [e.message for e in SERVER.iter_errors(msg)][:2])
        out.append(msg)
        if msg["type"] == type_:
            return out
    raise AssertionError(f"no {type_} in {limit} messages: {[m['type'] for m in out]}")


def test_health():
    with TestClient(app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_hello_then_lobby():
    with TestClient(app) as client, client.websocket_connect("/ws/abc-123") as ws:
        assert ws.receive_json() == {"type": "hello", "session": "abc-123"}
        assert ws.receive_json() == {"type": "session_state", "phase": "lobby", "turn": 0}


def test_bad_messages_get_an_error_and_change_nothing():
    with TestClient(app) as client, client.websocket_connect("/ws/dev") as ws:
        receive_until(ws, "session_state")
        ws.send_text("not json")
        assert receive_until(ws, "error")[-1]["code"] == "bad_json"
        ws.send_bytes(b"\x00\x01")
        assert receive_until(ws, "error")[-1]["code"] == "bad_json"
        ws.send_json({"type": "turn_submit", "channels": {"speech": "hi"}})  # no source
        assert receive_until(ws, "error")[-1]["code"] == "bad_message"
        ws.send_json({"type": "turn_submit", "channels": {"speech": "hi"}, "source": "filled"})  # not started
        assert receive_until(ws, "error")[-1]["code"] == "not_playing"


def test_play_two_turns_over_the_socket():
    with TestClient(app) as client, client.websocket_connect("/ws/play") as ws:
        receive_until(ws, "session_state")
        ws.send_json({"type": "session_start", "name": "Sam", "gender": "female"})
        msgs = receive_until(ws, "passage")
        assert msgs[-1]["turn"] == 0 and msgs[-1]["player"] is None
        assert "I ring the bell." in " ".join(s["text"] for s in msgs[-1]["segments"])
        assert sum(m["type"] == "phone_event" for m in msgs) == 3
        receive_until(ws, "drama_state")

        ws.send_json({"type": "input_review", "mode": "single", "text": 'I smile. "Hi, Mia."'})
        review = receive_until(ws, "input_review_result")[-1]
        assert review["verdict"] == "ok" and review["channels"]["speech"] == "Hi, Mia."
        ws.send_json({"type": "turn_submit", "channels": review["channels"], "source": "typed_accepted", "review_id": review["review_id"]})
        msgs = receive_until(ws, "passage")
        assert msgs[0] == {"type": "turn_accepted", "turn": 1}
        assert msgs[-1]["player"]["speech"] == "Hi, Mia."
        trace = receive_until(ws, "turn_trace")[-1]
        assert trace["record"]["input"]["review_id"] == review["review_id"]
        receive_until(ws, "drama_state")

        ws.send_json({"type": "options_request"})
        assert len(receive_until(ws, "options")[-1]["items"]) == 3

        ws.send_json({"type": "input_review", "mode": "single", "text": "Julian admits everything."})
        rejected = receive_until(ws, "input_review_result")[-1]
        assert rejected["verdict"] == "rejected" and rejected["category"] == "npc_action" and rejected["rewrite"]

    with TestClient(app) as client:
        state = client.get("/api/sessions/play/state").json()
        assert state["state"]["turn_count"] == 1
        assert len(client.get("/api/sessions/play/turns").json()) == 2


def test_reconnect_resumes_the_session():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/again") as ws:
            receive_until(ws, "session_state")
            ws.send_json({"type": "session_start", "name": "Sam", "gender": "male"})
            receive_until(ws, "drama_state")
        with client.websocket_connect("/ws/again") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert ws.receive_json() == {"type": "session_state", "phase": "playing", "turn": 0}


def test_intro_serves_the_premise_and_the_cards():
    with TestClient(app) as client:
        intro = client.get("/api/intro").json()
    assert [c["id"] for c in intro["cast"]] == ["julian", "mia", "leo", "nora"]
    assert {c["gender"] for c in intro["player"]["cards"]} == {"female", "male"}
    assert intro["premise"] and intro["title"] == "Fragile"


def test_the_play_screen_never_receives_console_state():
    with TestClient(app) as client, client.websocket_connect("/ws/player?mode=play") as ws:
        receive_until(ws, "session_state")
        ws.send_json({"type": "session_start", "name": "Sam", "gender": "female"})
        receive_until(ws, "room_state")
        ws.send_json({"type": "phone_open"})
        ws.send_json({"type": "options_request"})
        types = [m["type"] for m in receive_until(ws, "options")]
        assert "drama_state" not in types and "turn_trace" not in types


def test_the_truth_waits_for_the_ending():
    with TestClient(app) as client, client.websocket_connect("/ws/truth") as ws:
        receive_until(ws, "session_state")
        ws.send_json({"type": "session_start", "name": "Sam", "gender": "female"})
        receive_until(ws, "drama_state")
        assert client.get("/api/sessions/truth/truth").status_code == 403
        main_mod.SESSIONS["truth"].phase = "ended"
        r = client.get("/api/sessions/truth/truth")
        assert r.status_code == 200 and r.json()["timeline"]


def test_art_is_served():
    with TestClient(app) as client:
        r = client.get("/art/portraits/leo.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_the_console_watches_a_game_without_taking_it_from_the_player():
    with TestClient(app) as client, client.websocket_connect("/ws/both?mode=play") as play:
        receive_until(play, "session_state")
        with client.websocket_connect("/ws/both?mode=console") as console:
            receive_until(console, "session_state")
            play.send_json({"type": "session_start", "name": "Sam", "gender": "male"})
            assert receive_until(play, "passage")[-1]["turn"] == 0
            console_msgs = receive_until(console, "drama_state")
            assert any(m["type"] == "passage" for m in console_msgs) and "arc" in console_msgs[-1]
            listed = client.get("/api/sessions").json()
            assert listed[0]["id"] == "both" and listed[0]["watchers"] == 2
            play.send_json({"type": "options_request"})
            assert "drama_state" not in [m["type"] for m in receive_until(play, "options")]
