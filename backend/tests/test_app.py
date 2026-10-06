from fastapi.testclient import TestClient

from app.main import app


def test_health():
    with TestClient(app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_websocket_says_hello_and_ignores_input():
    with TestClient(app) as client, client.websocket_connect("/ws/dev") as ws:
        assert ws.receive_json() == {"type": "hello", "session": "dev"}
        # M0 ignores incoming messages; the connection stays open and nothing comes back.
        ws.send_json({"type": "turn_submit", "channels": {"speech": "hi"}})
        ws.send_text("not json")
        ws.send_bytes(b"\x00\x01")


def test_websocket_session_id_is_echoed():
    with TestClient(app) as client, client.websocket_connect("/ws/abc-123") as ws:
        assert ws.receive_json() == {"type": "hello", "session": "abc-123"}
